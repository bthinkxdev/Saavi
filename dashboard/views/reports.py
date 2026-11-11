"""Reports & analytics: charts, tables, CSV export, and manual recompute."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from dashboard import selectors
from dashboard.access import dashboard_required
from orders.models import Order
from orders.services import REVENUE_ORDER_STATUSES
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from reports.selectors import (
    get_admin_dashboard_summary,
    get_daily_customer_reports,
    get_daily_sales_reports,
    get_live_today_sales_report,
    get_live_today_customer_report,
)
from reports.services import aggregate_daily_reports


def _parse_date(value: str, default: date) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return default


@dashboard_required
def reports_view(request: HttpRequest) -> HttpResponse:
    """Analytics dashboard over the pre-aggregated report tables."""
    if "clear" in request.GET:
        request.session.pop("reports_start", None)
        request.session.pop("reports_end", None)
        return redirect("dashboard:reports")

    today = timezone.localdate()
    
    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    
    if start_str is not None and end_str is not None:
        request.session["reports_start"] = start_str
        request.session["reports_end"] = end_str
    else:
        start_str = request.session.get("reports_start", "")
        end_str = request.session.get("reports_end", "")
        
    start = _parse_date(start_str, today - timedelta(days=31))
    end = _parse_date(end_str, today)
    
    #safeguard against future dates
    if end > today:
        end = today
    if start > end:
        start = end

    sales = get_daily_sales_reports(start_date=start, end_date=end, page=1, page_size=366)
    customers = get_daily_customer_reports(start_date=start, end_date=end, page=1, page_size=366)

    if start <= today <= end:
        sales["results"] = [r for r in sales["results"] if r.report_date != today]
        sales["results"].insert(0, get_live_today_sales_report())
        customers["results"] = [r for r in customers["results"] if r.report_date != today]
        customers["results"].insert(0, get_live_today_customer_report())

    #currency metrics from live Order for INR | AED separation
    orders_qs = Order.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end, order_status__in=REVENUE_ORDER_STATUSES
    )
    daily_curr = {}
    for r in orders_qs.annotate(d=TruncDate("created_at")).values("d", "currency__code").annotate(rev=Sum("total_amount"), cnt=Count("id")):
        d = r["d"]
        daily_curr.setdefault(d, {"INR": {"rev": 0.0, "cnt": 0}, "AED": {"rev": 0.0, "cnt": 0}})
        daily_curr[d][r["currency__code"] or "INR"] = {"rev": float(r["rev"] or 0), "cnt": r["cnt"] or 0}

    sales_rows = []
    for r in sales["results"]:
        m = daily_curr.get(r.report_date, {"INR": {"rev": 0.0, "cnt": 0}, "AED": {"rev": 0.0, "cnt": 0}})
        inr_r, inr_c = m["INR"]["rev"], m["INR"]["cnt"]
        aed_r, aed_c = m["AED"]["rev"], m["AED"]["cnt"]
        sales_rows.append({
            "report_date": r.report_date,
            "orders": f"IN {inr_c} | AE {aed_c}",
            "revenue": f"₹ {inr_r:.2f} | AED {aed_r:.2f}",
            "aov": f"₹ {(inr_r / inr_c if inr_c else 0):.2f} | AED {(aed_r / aed_c if aed_c else 0):.2f}",
        })

    ordered = list(reversed(sales["results"]))
    
    #make chart timeline continuous between start and end
    chart_categories = []
    chart_revenue = []
    chart_revenue_disp = []
    chart_orders = []
    chart_returning = []
    
    #create a lookup for quick access
    sales_by_date = {r.report_date: r for r in ordered}
    customers_by_date = {r.report_date: r for r in customers["results"]}
    
    current_date = start
    while current_date <= end:
        chart_categories.append(current_date.strftime("%b %d"))
        m = daily_curr.get(current_date, {"INR": {"rev": 0.0, "cnt": 0}, "AED": {"rev": 0.0, "cnt": 0}})
        inr_r, aed_r = m["INR"]["rev"], m["AED"]["rev"]
        chart_revenue.append(inr_r + aed_r)
        chart_revenue_disp.append(f"₹ {inr_r:.2f} | AED {aed_r:.2f}")
        chart_orders.append(m["INR"]["cnt"] + m["AED"]["cnt"])
        c_row = customers_by_date.get(current_date)
        chart_returning.append(c_row.returning_customers if c_row else 0)
        current_date += timedelta(days=1)

    chart = {
        "categories": chart_categories,
        "revenue": chart_revenue,
        "revenue_display": chart_revenue_disp,
        "orders": chart_orders,
        "returning_customers": chart_returning,
    }

    range_curr = selectors.get_currency_metrics(orders_qs)
    today_curr = selectors.get_currency_metrics(
        Order.objects.filter(created_at__date=today, order_status__in=REVENUE_ORDER_STATUSES)
    )

    context = {
        "nav_section": "reports",
        "page_title": "Reports",
        "start": start,
        "end": end,
        "summary": get_admin_dashboard_summary(),
        "sales": sales_rows,
        "customers": customers["results"],
        "sales_series": chart,
        "display_rev": f"₹ {range_curr['INR']['revenue']:.0f} | AED {range_curr['AED']['revenue']:.2f}",
        "display_orders": f"IN {range_curr['INR']['orders']} | AE {range_curr['AED']['orders']}",
        "display_today": f"₹ {today_curr['INR']['revenue']:.0f} | AED {today_curr['AED']['revenue']:.2f}",
        "total_revenue": sum(float(r.revenue) for r in sales["results"]),
        "total_orders": sum(r.order_count for r in sales["results"]),
    }
    return render(request, "dashboard/reports/index.html", context)


@dashboard_required
def reports_export_csv(request: HttpRequest) -> HttpResponse:
    """Export daily sales in the selected range as CSV."""
    today = timezone.localdate()
    start_str = request.GET.get("start") or request.session.get("reports_start", "")
    end_str = request.GET.get("end") or request.session.get("reports_end", "")
    
    end = _parse_date(end_str, today)
    start = _parse_date(start_str, today - timedelta(days=31))
    
    if end > today:
        end = today
    if start > end:
        start = end
        
    sales = get_daily_sales_reports(start_date=start, end_date=end, page=1, page_size=366)

    if start <= today <= end:
        sales["results"] = [r for r in sales["results"] if r.report_date != today]
        sales["results"].insert(0, get_live_today_sales_report())

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="sales_{start}_{end}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Date", "Orders", "Revenue", "Avg order value", "Coupon discount"])
    for r in sales["results"]:
        writer.writerow(
            [
                r.report_date,
                r.order_count,
                r.revenue,
                r.average_order_value,
                r.coupon_discount_total,
            ]
        )
    return response


@dashboard_required
@require_POST
def reports_recompute(request: HttpRequest) -> HttpResponse:
    """Manually re-run aggregation for a given date (default: yesterday)."""
    target = _parse_date(request.POST.get("date", ""), timezone.localdate() - timedelta(days=1))
    try:
        aggregate_daily_reports(report_date=target)
        messages.success(request, f"Reports recomputed for {target}.")
    except Exception as exc:  # noqa: BLE001 - surface any aggregation failure to admin
        messages.error(request, f"Recompute failed: {exc}")
    return redirect("dashboard:reports")
