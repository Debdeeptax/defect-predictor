"""Legacy monthly report builder.

Sample of the long, branch-heavy "god function" style that defect models flag as
high risk (size and complexity together). Kept deliberately unrefactored.
"""
import csv
import datetime
import os


def build_monthly_report(rows, out_dir, month=None, currency="USD", include_refunds=True,
                         group_by="region", min_amount=0, fmt="csv", verbose=False):
    # Resolve month
    if month is None:
        today = datetime.date.today()
        month = today.replace(day=1) - datetime.timedelta(days=1)
        month = month.strftime("%Y-%m")

    totals = {}
    counts = {}
    refunds = {}
    errors = []
    skipped = 0

    # Pass 1: aggregate
    for i, row in enumerate(rows):
        if not row:
            skipped += 1
            continue
        date = row.get("date", "")
        if not date.startswith(month):
            skipped += 1
            continue
        try:
            amount = float(row.get("amount", 0))
        except (TypeError, ValueError):
            errors.append((i, "bad amount"))
            continue
        if amount < min_amount and amount >= 0:
            skipped += 1
            continue

        key = row.get(group_by) or "unknown"
        if group_by == "region" and key not in ("EU", "US", "IN", "APAC"):
            key = "other"
        elif group_by == "product" and len(key) > 40:
            key = key[:40]

        if row.get("currency", currency) != currency:
            rate = row.get("fx_rate")
            if rate is None:
                errors.append((i, "missing fx"))
                continue
            try:
                amount = amount * float(rate)
            except (TypeError, ValueError):
                errors.append((i, "bad fx"))
                continue

        if amount < 0:
            if include_refunds:
                refunds[key] = refunds.get(key, 0) + amount
            else:
                skipped += 1
                continue
        else:
            totals[key] = totals.get(key, 0) + amount
            counts[key] = counts.get(key, 0) + 1

    # Pass 2: derive figures
    lines = []
    grand_total = 0
    for key in sorted(set(totals) | set(refunds)):
        gross = totals.get(key, 0)
        ref = refunds.get(key, 0)
        net = gross + ref
        n = counts.get(key, 0)
        avg = gross / n if n else 0
        if net < 0 and verbose:
            print(f"warning: negative net for {key}")
        share = None
        lines.append([key, round(gross, 2), round(ref, 2), round(net, 2), n, round(avg, 2), share])
        grand_total += net

    for line in lines:
        if grand_total:
            line[6] = round(100 * line[3] / grand_total, 1)
        else:
            line[6] = 0.0

    # Output
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    name = f"report_{month}_{group_by}.{fmt}"
    path = os.path.join(out_dir, name)
    header = [group_by, "gross", "refunds", "net", "count", "avg", "share_pct"]

    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for line in lines:
                w.writerow(line)
            w.writerow(["TOTAL", "", "", round(grand_total, 2), "", "", 100.0 if grand_total else 0])
    elif fmt == "txt":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(" | ".join(header) + "\n")
            for line in lines:
                fh.write(" | ".join("" if v is None else str(v) for v in line) + "\n")
            fh.write(f"TOTAL {round(grand_total, 2)} {currency}\n")
    elif fmt == "md":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("| " + " | ".join(header) + " |\n")
            fh.write("|" + "---|" * len(header) + "\n")
            for line in lines:
                fh.write("| " + " | ".join(str(v) for v in line) + " |\n")
    else:
        raise ValueError(f"unknown format {fmt}")

    if verbose:
        print(f"{len(lines)} groups, {skipped} skipped, {len(errors)} errors -> {path}")
        for idx, reason in errors[:20]:
            print(f"  row {idx}: {reason}")

    return {"path": path, "groups": len(lines), "skipped": skipped, "errors": errors,
            "total": round(grand_total, 2)}
