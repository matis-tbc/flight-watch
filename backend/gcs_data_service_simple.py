#!/usr/bin/env python3
"""gcs data service - csv module, no pandas"""
import os
import csv
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from io import StringIO

logger = logging.getLogger(__name__)

class GCSDataServiceSimple:
    """read flight data from gcs using csv module"""
    
    def __init__(self):
        self.project_id = os.getenv('GCP_PROJECT_ID', 'flightwatch-486618')
        self.bucket_name = os.getenv('GCS_BUCKET')
        self.file_path = os.getenv('GCS_FILE_PATH')
        self.data_cache = None
        self.last_load_time = None
        self.column_names = []
        
    def is_configured(self) -> bool:
        return bool(self.bucket_name and self.file_path)
    
    def load_data_from_gcs(self) -> Optional[List[Dict[str, Any]]]:
        """load flight data from gcs bucket using csv"""
        if not self.is_configured():
            logger.warning("gcs not configured - check GCS_BUCKET and GCS_FILE_PATH in .env")
            return None
        
        try:
            from google.cloud import storage
            
            logger.info(f"loading flight data from gcs: gs://{self.bucket_name}/{self.file_path}")
            
            client = storage.Client(project=self.project_id)
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(self.file_path)
            
            # Download file content
            content = blob.download_as_text()
            
            # Parse CSV using built-in csv module
            csv_reader = csv.DictReader(StringIO(content))
            
            # Get column names
            self.column_names = csv_reader.fieldnames or []
            
            # Convert to list of dicts
            flight_data = list(csv_reader)
            
            logger.info(f"✅ Loaded {len(flight_data)} flight records from GCS")
            logger.info(f"📊 Columns: {self.column_names}")
            
            self.data_cache = flight_data
            self.last_load_time = datetime.now()
            
            return flight_data
            
        except ImportError:
            logger.error("GCS dependencies not installed. Run: pip install google-cloud-storage")
            return None
        except Exception as e:
            logger.error(f"❌ Error loading data from GCS: {e}")
            return None
    
    def search_flights(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        departure_date: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """search flights in gcs data"""
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
            filtered = [f for f in filtered if self._get_field(f, 'origin', 'origin_location', 'origin_code').upper() == origin]
        
        if destination:
            destination = destination.upper()
            filtered = [f for f in filtered if self._get_field(f, 'destination', 'dest_location', 'dest_code').upper() == destination]
        
        if departure_date:
            filtered = [f for f in filtered if self._get_field(f, 'departure_datetime', 'departure_date', 'date', 'departure').startswith(departure_date)]
        
        return filtered[:limit]
    
    def _get_field(self, record: Dict[str, Any], *field_names: str) -> str:
        """get field with fallback names"""
        for field in field_names:
            if field in record:
                value = record[field]
                return str(value) if value is not None else ""
        return ""
    
    def get_available_origins(self) -> List[str]:
        """get unique origin airports"""
        if self.data_cache is None:
            self.load_data_from_gcs()
        
        if not self.data_cache:
            return []
        
        origins = set()
        for flight in self.data_cache:
            origin = self._get_field(flight, 'origin', 'origin_location', 'origin_code')
            if origin:
                origins.add(origin.upper())
        
        return sorted(origins)
    
    def get_available_destinations(self) -> List[str]:
        """Get list of unique destination airports in data"""
        if self.data_cache is None:
            self.load_data_from_gcs()
        
        if not self.data_cache:
            return []
        
        destinations = set()
        for flight in self.data_cache:
            dest = self._get_field(flight, 'destination', 'dest_location', 'dest_code')
            if dest:
                destinations.add(dest.upper())
        
        return sorted(destinations)
    
    def get_data_summary(self) -> Dict[str, Any]:
        """Get summary of GCS data"""
        if self.data_cache is None:
            self.load_data_from_gcs()
        
        if not self.data_cache:
            return {
                "status": "no_data",
                "message": "No flight data loaded from GCS"
            }
        
        # Sample first record
        sample = self.data_cache[0] if self.data_cache else {}
        
        return {
            "status": "loaded",
            "record_count": len(self.data_cache),
            "columns": self.column_names,
            "origins_available": len(self.get_available_origins()),
            "destinations_available": len(self.get_available_destinations()),
            "sample_record": {k: sample.get(k, '') for k in list(sample.keys())[:5]},
            "last_loaded": self.last_load_time.isoformat() if self.last_load_time else None,
            "source": f"gs://{self.bucket_name}/{self.file_path}",
            "parser": "csv_module (pandas-free)"
        }


# Create singleton instance
gcs_data_service_simple = GCSDataServiceSimple()

if __name__ == "__main__":
    # Test the service
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    
    service = GCSDataServiceSimple()
    
    if service.is_configured():
        print("✅ GCS configured")
        summary = service.get_data_summary()
        print(f"Data summary: {summary}")
        
        # Test search
        flights = service.search_flights(limit=3)
        print(f"\nSample flights ({len(flights)}):")
        for i, flight in enumerate(flights):
            print(f"  {i+1}. Origin: {service._get_field(flight, 'origin')}, Dest: {service._get_field(flight, 'destination')}")
    else:
        print("❌ GCS not configured")
        print("Add to .env:")
        print("  GCS_BUCKET=your-bucket-name")
        print("  GCS_FILE_PATH=path/to/flight_data.csv")
        print("\nAsk your team for bucket name and file path")