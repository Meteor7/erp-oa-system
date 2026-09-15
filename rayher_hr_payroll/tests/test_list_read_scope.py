import pytest
from concurrent.futures import ThreadPoolExecutor
from rayher_hr_payroll.list_read_scope import active, read_scope, reuse

def test_reuses_once_but_returns_independent_objects():
    calls=[]
    @read_scope
    def run():
        def load(): calls.append(1); return {"user":"a"}
        first=reuse("role",load);first["user"]="changed"
        assert reuse("role",load)=={"user":"a"}
    run();assert len(calls)==1
    run();assert len(calls)==2

def test_outside_scope_reads_fresh():
    calls=[]
    def load(): calls.append(1); return len(calls)
    assert reuse("key",load)==1
    assert reuse("key",load)==2

def test_failure_clears_scope():
    @read_scope
    def run():
        reuse("x",lambda:1)
        raise ValueError()
    with pytest.raises(ValueError):run()
    assert not active()
    assert reuse("x",lambda:2)==2

def test_errors_not_cached():
    @read_scope
    def run():
        def fail():raise ValueError()
        with pytest.raises(ValueError):reuse("x",fail)
        assert reuse("x",lambda:2)==2
    run()

def test_nested_scopes_restore_parent():
    @read_scope
    def inner():assert reuse("x",lambda:2)==2
    @read_scope
    def outer():
        assert reuse("x",lambda:1)==1
        inner()
        assert reuse("x",lambda:3)==1
    outer()

def test_parallel_calls_do_not_share_cache():
    @read_scope
    def run(value):return reuse("same-role",lambda:value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run,["alice","bob"]))==["alice","bob"]
