import csv
from datetime import date

from django.http import HttpResponse


def export_csv(report):
    filename = f"{report['slug']}_{date.today().isoformat()}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow([report["definition"].title])
    for label, value in report["summary"]:
        writer.writerow([label, value])
    writer.writerow([])
    writer.writerow(report["headers"])
    for row in report["rows"]:
        writer.writerow(row)
    return response
