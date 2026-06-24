frappe.query_reports["RD Allocation Matrix"] = {
	filters: [
		{
			fieldname: "allocation",
			label: __("分摊单"),
			fieldtype: "Link",
			options: "RD Cost Allocation",
			reqd: 0,
			get_query: () => ({ filters: { docstatus: 1 } }),
		},
	],
	onload(report) {
		if (!report.get_filter_value("allocation")) {
			frappe.db
				.get_list("RD Cost Allocation", {
					filters: { docstatus: 1 },
					fields: ["name"],
					order_by: "creation desc",
					limit: 1,
				})
				.then((rows) => {
					if (rows && rows.length) {
						report.set_filter_value("allocation", rows[0].name);
					}
				});
		}
	},
};
