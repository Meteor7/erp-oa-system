"""Batch procurement inputs and cache pure summaries by their exact dependencies.

No permission decisions are cached. Database inputs remain the authority, including
direct SQL updates and transaction-local changes. Content-addressed keys prevent a
slow/rolled-back writer from poisoning a newer summary. Only list reads opt in.
"""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json

import frappe
import redis

_values = ContextVar("procurement_summaries", default=None)
_clients = {}
PREFIX = "procurement-summary:v1:"
TTL = 3600


def prepared_summary(name):
    values = _values.get()
    return deepcopy(values.get(name)) if values is not None else None


def _client():
    site = frappe.local.site
    if site not in _clients:
        options = dict(frappe.cache().connection_pool.connection_kwargs)
        options.update(socket_timeout=0.25, socket_connect_timeout=0.25,
                       retry_on_timeout=False)
        _clients[site] = redis.Redis(connection_pool=redis.ConnectionPool(**options))
    return _clients[site]


def _read_inputs(docs):
    names = [doc.name for doc in docs]
    if not names:
        return {}
    grouped = [defaultdict(list) for _ in range(3)]
    for index, doctype in enumerate(("OA Procurement Request Line",
                                    "OA Price Approval Line", "OA Purchase Order Line")):
        fields = ["source_request", "parent", "source_line", "quantity"]
        if index == 0:
            fields.append("remaining_quantity")
        for row in frappe.get_all(doctype, filters={"source_request": ["in", names]},
                                  fields=fields, order_by="name asc", limit_page_length=0):
            grouped[index][row.source_request].append(row)
    statuses = []
    for index, doctype in ((1, "OA Price Approval"), (2, "OA Purchase Order")):
        parents = sorted({row.parent for rows in grouped[index].values() for row in rows if row.parent})
        statuses.append({
            row.name: str(row.status or "").strip()
            for row in (frappe.get_all(doctype, filters={"name": ["in", parents]},
                        fields=["name", "status"], limit_page_length=0) if parents else [])
        })
    data = {}
    for doc in docs:
        pr, prices, pos = (group[doc.name] for group in grouped)
        prices = [row for row in prices
                  if row.parent in statuses[0] and statuses[0][row.parent] != "已取消"]
        price_status = {row.parent: statuses[0][row.parent] for row in prices}
        po_status = {row.parent: statuses[1][row.parent] for row in pos if row.parent in statuses[1]}
        data[doc.name] = (pr, prices, pos, price_status, po_status)
    return data


def _key(doc, data):
    inputs = {
        "name": doc.name, "type": doc.request_type,
        "workflow": doc.workflow_status, "business": doc.business_status,
        "lines": [(row.name, row.quantity) for row in doc.business_lines or []],
        "chain": data,
    }
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str,
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    return frappe.cache().make_key(PREFIX + doc.name + ":" + digest)


@contextmanager
def prepare_summaries(docs, calculate):
    # Non-procurement and unapproved requests use the original cheap path.
    eligible = [doc for doc in docs if doc.request_type == "采购申请" and (
        str(doc.business_status or "").strip().startswith("需求已批准")
        or doc.workflow_status in {"已完成", "已通过", "已审批", "已结束"})]
    summaries = {}
    if eligible:
        try:
            inputs = _read_inputs(eligible)
        except Exception:
            # Retain the old fallback for sites without these optional doctypes.
            inputs = None
        if inputs is not None:
            keys = [_key(doc, inputs[doc.name]) for doc in eligible]
            client = None
            try:
                client = _client()
                cached = client.mget(keys)
            except Exception:
                cached = [None] * len(keys)
            writes = []
            for doc, key, value in zip(eligible, keys, cached):
                result = None
                if value:
                    try:
                        candidate = json.loads(value)
                        if isinstance(candidate, dict) and {
                            "stage", "label", "summary", "pr_numbers",
                            "price_approval_numbers", "po_numbers", "pending_pr_lines",
                            "pending_price_lines", "draft_price_lines", "approval_lines",
                            "po_lines",
                        } == set(candidate):
                            result = candidate
                    except (ValueError, TypeError):
                        pass
                if result is None:
                    result = calculate(doc, data=inputs[doc.name])
                    writes.append((key, json.dumps(result, ensure_ascii=False)))
                summaries[doc.name] = result
            if writes and client is not None:
                try:
                    pipe = client.pipeline(transaction=False)
                    for key, value in writes:
                        pipe.set(key, value, ex=TTL)
                    pipe.execute()
                except Exception:
                    pass
    token = _values.set(summaries)
    try:
        yield
    finally:
        _values.reset(token)
