"""Station-level prevention advice from explicitly supplied field measurements.

These configurable prototype thresholds describe inspection urgency, not fire probability.
Rainfall is optional; missing daily values never become zero rainfall.
"""

from app.schemas.prevention import PreventionDecision, PreventionRequest

PREVENTION_RULE_VERSION = "field-prevention-1.0"
GWT_REFERENCE_M = -0.4
DECLINE_M = -0.05
LOW_RAIN_7D_MM = 10


def assess_prevention(request: PreventionRequest, *, fresh: bool) -> PreventionDecision:
    rows = request.readings
    latest = rows[-1].gwt_m
    delta = round(latest - rows[0].gwt_m, 6)
    rain = [row.rainfall_mm for row in rows if row.rainfall_mm is not None]
    total = round(sum(rain), 3) if len(rain) == 7 else None
    dry_days = None
    if total is not None:
        dry_days = 0
        for value in reversed(rain):
            if value >= 1:
                break
            dry_days += 1
    missing = [] if total is not None else ["Curah hujan harian belum lengkap (7 hari)."]
    reasons = [f"GWT terakhir {latest:.3f} m; perubahan selama 7 tanggal {delta:+.3f} m."]
    if total is not None:
        reasons.append(f"Curah hujan 7 hari {total:.1f} mm; {dry_days} hari terakhir <1 mm/hari.")
    else:
        reasons.append("Curah hujan belum lengkap; penilaian hanya memakai GWT.")
    if not fresh:
        return PreventionDecision(
            priority="INSUFFICIENT_DATA",
            explanation="Pengukuran terakhir lebih dari dua hari lalu; perbarui data lapangan.",
            reasons=reasons,
            recommended_actions=["Lakukan pengukuran GWT terbaru sebelum menentukan tindakan."],
            missing_inputs=[*missing, "GWT terbaru (maksimal berumur 2 hari)."],
            latest_gwt_m=latest, change_m=delta, rainfall_7d_mm=total,
            rainfall_days=len(rain), dry_spell_days=dry_days,
            reference_gwt_m=GWT_REFERENCE_M, rule_version=PREVENTION_RULE_VERSION,
        )
    low = latest <= GWT_REFERENCE_M
    declining = delta <= DECLINE_M
    dry = total is not None and total < LOW_RAIN_7D_MM
    actions = []
    if low:
        reasons.append("GWT mencapai/melewati acuan prototipe −0,40 m.")
        actions.append("Minta petugas mengukur ulang GWT dan memeriksa kondisi tata air/kanal.")
    if declining:
        reasons.append("Muka air turun setidaknya 5 cm selama jendela pengukuran.")
        actions.append("Tingkatkan pemantauan harian dan catat perubahan berikutnya.")
    if dry:
        reasons.append("Hujan kurang dari 10 mm/7 hari pada acuan prototipe.")
        actions.append("Prioritaskan patroli pencegahan dan pemeriksaan lapangan saat kering.")
    priority = "HIGH" if low and (declining or dry) else (
        "MEDIUM" if low or declining or dry else "LOW"
    )
    if not actions:
        actions.append("Lanjutkan pengukuran harian dan tinjau ulang bila muka air turun.")
    if total is None:
        actions.append("Lengkapi pengukuran hujan untuk menilai konteks kekeringan.")
    return PreventionDecision(
        priority=priority,
        explanation={
            "HIGH": "Prioritaskan pemeriksaan: muka air rendah disertai penurunan/hujan minim.",
            "MEDIUM": "Ada indikator yang perlu dipantau dan diperiksa oleh petugas.",
            "LOW": "Lanjutkan pemantauan rutin; hasil ini bukan jaminan tidak terjadi kebakaran.",
        }[priority],
        reasons=reasons, recommended_actions=actions, missing_inputs=missing,
        latest_gwt_m=latest, change_m=delta, rainfall_7d_mm=total,
        rainfall_days=len(rain), dry_spell_days=dry_days,
        reference_gwt_m=GWT_REFERENCE_M, rule_version=PREVENTION_RULE_VERSION,
    )
