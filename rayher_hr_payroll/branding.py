"""Presentation-only branding for the portfolio sign-in page."""

def update_website_context(context):
    if context.get("path") != "login":
        return
    context.update({
        "app_name": "栖衡 ERP / OA",
        "title": "登录 · 栖衡 ERP / OA",
        "logo": "/assets/rayher_hr_payroll/images/qiheng-logo-light.svg",
        "favicon": "/assets/rayher_hr_payroll/images/qiheng-icon.svg",
    })
