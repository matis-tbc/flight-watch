#!/usr/bin/env python3
"""GCS data service using the builtin csv module."""
import csv
import logging
import os
from datetime import datetime
from io import StringIO
from typing import Any, Dict, List, Optional

from .gcp_auth import resolve_google_application_credentials

logger = logging.getLogger(__name__)


class GCSDataServiceSimple:
    """Read flight data from GCS using the csv module."""

    def __init__(self):
        self.project_id = os.getenv("GCP_PROJECT_ID", "flightwatch-486618")
        self.bucket_name = os.getenv("GCS_BUCKET")
        self.file_path = os.getenv("GCS_FILE_PATH")
        self.data_cache = None
        self.last_load_time = None
        self.column_names = []

    def is_configured(self) -> bool:
        return bool(self.bucket_name and self.file_path)

    def load_data_from_gcs(self) -> Optional[List[Dict[str, Any]]]:
        if not self.is_configured():
            logger.warning("gcs not configured - check GCS_BUCKET and GCS_FILE_PATH in .env")
            return None

        try:
            from google.cloud import storage

            resolve_google_application_credentials()
            logger.info(f"loading flight data from gcs: gs://{self.bucket_name}/{self.file_path}")

            client = storage.Client(project=self.project_id)
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(self.file_path)
            content = blob.download_as_text()

            csv_reader = csv.DictReader(StringIO(content))
            self.column_names = csv_reader.fieldnames or []
            flight_data = list(csv_reader)

            logger.info(f"Loaded {len(flight_data)} flight records from GCS")
            logger.info(f"Columns: {self.column_names}")

            self.data_cache = flight_data
            self.last_load_time = datetime.now()
            return flight_data

        except ImportError:
            logger.error('GCS dependencies not installed. Run: python -m pip install -e ".[backend]"')
            return None
        except Exception as error:
            logger.error(f"Error loading data from GCS: {error}")
            return None

    def search_flights(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        departure_date: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        if self.data_cache is None:
            flight_data = self.load_data_from_gcs()
            if flight_data is None:
                return []
        else:
            flight_data = self.data_cache

        if not flight_data:
            return []

        filtered = flight_data

        if origin:
            origin = origin.upper()
            filtered = [f for f in filtered if self._get_field(f, "origin", "origin_location", "origin_code").upper() == origin]

        if destination:
            destination = destination.upper()
            filtered = [f for f in filtered if self._get_field(f, "destination", "dest_location", "dest_code").upper() == destination]

        if departure_date:
            def matches_date(record):
                raw = self._get_field(record, "departure_datetime", "departure_date", "date", "departure")
                raw = raw.strip()
                return raw.startswith(departure_date) or departure_date in raw

            filtered = [f for f in filtered if matches_date(f)]

        return filtered[:limit]

    def _extract_price(self, record: Dict[str, Any]):
        for field in ("total_price", "price", "flight_price"):
            raw = record.get(field)
            if raw is None:
                continue
            if isinstance(raw, dict):
                raw = raw.get("total")
            try:
                return float(str(raw).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
        return None

    def explore_destinations(
        self,
        origin: str,
        max_price: float,
        departure_date: str = None,
    ) -> List[Dict[str, Any]]:
        if self.data_cache is None:
            flight_data = self.load_data_from_gcs()
            if flight_data is None:
                return []
        else:
            flight_data = self.data_cache

        if not flight_data:
            return []

        origin = origin.upper()
        filtered = [
            f for f in flight_data
            if self._get_field(f, "origin", "origin_location", "origin_code").upper() == origin
        ]

        if departure_date:
            filtered = [
                f for f in filtered
                if self._get_field(f, "departure_datetime", "departure_date", "date", "departure").startswith(departure_date)
            ]

        dest_map = {}
        for flight in filtered:
            price = self._extract_price(flight)
            if price is None or price > max_price:
                continue
            dest = self._get_field(flight, "destination", "dest_location", "dest_code").upper()
            if not dest:
                continue
            if dest not in dest_map:
                dest_map[dest] = {"cheapest": price, "flight": flight, "count": 0}
            dest_map[dest]["count"] += 1
            if price < dest_map[dest]["cheapest"]:
                dest_map[dest]["cheapest"] = price
                dest_map[dest]["flight"] = flight

        results = []
        for dest, info in dest_map.items():
            flight = info["flight"]
            results.append({
                "destination": dest,
                "cheapest_price": info["cheapest"],
                "currency": self._get_field(flight, "currency") or "USD",
                "airline": self._get_field(flight, "airline_code", "airline") or "Unknown",
                "flight_count": info["count"],
                "sample_flight": flight,
            })

        results.sort(key=lambda x: x["cheapest_price"])
        return results

    def _get_field(self, record: Dict[str, Any], *field_names: str) -> str:
        normalized = {
            str(key).strip().lower().replace("\ufeff", ""): value
            for key, value in record.items()
        }
        for field in field_names:
            key = field.strip().lower()
            if key in normalized:
                value = normalized[key]
                return str(value).strip() if value is not None else ""
        return ""

    def get_available_origins(self) -> List[str]:
        if self.data_cache is None:
            self.load_data_from_gcs()

        if not self.data_cache:
            return []

        origins = set()
        for flight in self.data_cache:
            origin = self._get_field(flight, "origin", "origin_location", "origin_code")
            if origin:
                origins.add(origin.upper())

        return sorted(origins)

    def get_available_destinations(self) -> List[str]:
        if self.data_cache is None:
            self.load_data_from_gcs()

        if not self.data_cache:
            return []

        destinations = set()
        for flight in self.data_cache:
            dest = self._get_field(flight, "destination", "dest_location", "dest_code")
            if dest:
                destinations.add(dest.upper())

        return sorted(destinations)

    def get_data_summary(self) -> Dict[str, Any]:
        if self.data_cache is None:
            self.load_data_from_gcs()

        if not self.data_cache:
            return {
                "status": "no_data",
                "message": "No flight data loaded from GCS",
            }

        sample = self.data_cache[0] if self.data_cache else {}

        return {
            "status": "loaded",
            "record_count": len(self.data_cache),
            "columns": self.column_names,
            "origins_available": len(self.get_available_origins()),
            "destinations_available": len(self.get_available_destinations()),
            "sample_record": {k: sample.get(k, "") for k in list(sample.keys())[:5]},
            "last_loaded": self.last_load_time.isoformat() if self.last_load_time else None,
            "source": f"gs://{self.bucket_name}/{self.file_path}",
            "parser": "csv_module (pandas-free)",
        }


gcs_data_service_simple = GCSDataServiceSimple()

