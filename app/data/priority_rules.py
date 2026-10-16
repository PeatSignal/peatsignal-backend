"""Versioned prototype rules. Priorities are inspection urgency, never fire probability."""

RULE_VERSION = "inspection-rules-1.0"
RULE_CONFIG = {"window_days": 7, "gwt_freshness_days": 2, "repeat_days": 3}


def evaluate(snapshot: dict) -> dict:
    missing = ["CHIRPS_RAINFALL"]
    reasons = []
    if not snapshot["gwt_trends"]:
        missing.append("GWT_TREND_7D")
    if not snapshot["supporting_reports"]:
        missing.append("FIELD_VERIFICATION")
    # No observations is not evidence of absence, even after a successful download.
    if not snapshot["hotspots"]:
        missing.append("HOTSPOT_EVIDENCE")
    declining = any(t["delta_m"] < 0 for t in snapshot["gwt_trends"])
    repeated = (
        len({h["acquired_at"][:10] for h in snapshot["hotspots"]}) >= RULE_CONFIG["repeat_days"]
    )
    if repeated:
        reasons.append("HOTSPOT_REPEATED_3_DAYS")
    if declining:
        reasons.append("REGIONAL_GWT_DECLINING")
    if repeated and snapshot["supporting_reports"]:
        decision, priority = "ESCALATE", "HIGH"
        reasons.append("FIELD_REPORT_SUPPORTS_INDICATION")
        explanation = "Hotspot berulang dan laporan terverifikasi mendukung pemeriksaan lanjutan."
        actions = ["Koordinator meninjau bukti dan menentukan pemeriksaan lanjutan."]
    elif any(not h["reviewed"] for h in snapshot["hotspots"]):
        decision, priority = "REVIEW", "HIGH" if repeated else "MEDIUM"
        reasons.append("HOTSPOT_REQUIRES_VERIFICATION")
        explanation = "Anomali termal memerlukan verifikasi; bukan konfirmasi kebakaran."
        actions = ["Buat tugas inspeksi dan verifikasi indikasi hotspot."]
    elif snapshot["gwt_trends"]:
        decision, priority = "MONITOR", "MEDIUM" if declining else "LOW"
        reasons.append("REGIONAL_GWT_TREND_AVAILABLE")
        explanation = "Tren GWT regional tersedia; belum dapat dikorelasikan dengan lokasi hotspot."
        actions = ["Pantau tren dan periksa tata air bila diperlukan."]
    else:
        decision, priority = "INSUFFICIENT_DATA", "INSUFFICIENT_DATA"
        reasons.append("INSUFFICIENT_CONTEMPORARY_INPUTS")
        explanation = "Data sezaman belum cukup untuk menentukan prioritas; bukan berarti aman."
        actions = ["Lengkapi data sezaman atau lakukan pemeriksaan lapangan."]
    return dict(
        decision=decision, priority=priority, reason_codes=reasons,
        missing_inputs=missing, explanation=explanation, recommended_actions=actions,
    )
