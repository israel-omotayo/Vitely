import logging
from django.db import connection
from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

def health(request):
    """
    Health check for UptimeRobot and Render.
    Probes PostgreSQL and Redis — returns 503 if either is down.
    """
    checks = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        logger.error("Health check: DB probe failed: %s", e)
        checks["db"] = "error"

    try:
        cache.set("health_check_ping", "pong", timeout=5)
        result = cache.get("health_check_ping")
        checks["cache"] = "ok" if result == "pong" else "error"
    except Exception as e:
        logger.error("Health check: Cache probe failed: %s", e)
        checks["cache"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    status = 200 if all_ok else 503
    label = "ok" if all_ok else "degraded"

    return JsonResponse({"status": label, "checks": checks}, status=status)

