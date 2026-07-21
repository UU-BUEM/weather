"""Sample python code to demonstrate how to use the
ECMWF Datastore Client and CDS API Client to retrieve ERA5-Land data.
"""
import logging

import cdsapi
from ecmwf.datastores import Client

logger = logging.getLogger(__name__)

url: str = "https://cds.climate.copernicus.eu/api"
key: str = "your_cds_api_key_here"

client = Client(url, key)


class ECMWFDatastoreClient:
    """
    Adapted from
    https://ecmwf.github.io/ecmwf-datastores-client/README.html
    """
    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key

    def collection(self):
        self.collection_id = "reanalysis-era5-template-attribute"
        self.request = {
            "product_type": ["reanalysis"],
            "variable": ["temperature"],
            "year": ["2022"],
            "month": ["01"],
            "day": ["01"],
            "time": ["00:00"],
            "pressure_level": ["1000"],
            "data_format": "grib",
            "download_format": "unarchived",
        }
        return client.retrieve(self.collection_id, self.request)

    def retrieve_data(self):
        remote = client.submit(
            self.collection_id,
            self.request
            )
        target = remote.download("target.grib")

        result = client.submit_and_wait_on_results(
            self.collection_id,
            self.request
        )
        target_1 = result.download("target_1.grib")

        target_2 = client.download_results(
            remote.request_id, "target_2.grib"
        )
        return target, target_1, target_2

    def sort_collectionIDs(self):
        collections = client.get_collections(sortby="update")

        collection_ids = []
        while collections is not None:  # Loop over pages
            collection_ids.extend(collections.collection_ids)
            collections = collections.next  # Move to the next page

        return collection_ids

    def explore_collection(self):
        collection = client.get_collection(
            self.collection_id
        )
        print(
            f"Collection_id: {collection.id}\n"
            f"Title: {collection.title}\n"
            f"Description: {collection.description}\n"
            f"Published at: {collection.published_at}\n"
            f"Updated at: {collection.updated_at}\n"
            f"Begin datetime: {collection.begin_datetime}\n"
            f"End datetime: {collection.end_datetime}\n"
        )

        submitted_request = collection.submit(self.request)
        constraints = collection.apply_constraints(self.request)

        print(
            f"Submitted request: {submitted_request}\n"
            f"Constraints: {constraints}\n"
        )

    def result_interaction(self):
        remote = client.submit(
            self.collection_id,
            self.request
        )
        results = client.get_results(remote.request_id)

        print(
            f"Result content length: {results.content_length}:\n"
            f"Result content type: {results.content_type}\n"
            f"Result location: {results.location}\n"
        )
        target_3 = results.results("target_3.grib")

        return target_3

    def list_successful_jobs(self):
        jobs = client.get_jobs(
            sortby="-created",
            status="successful"
        )

        request_ids = []

        while jobs is not None:  # Loop over pages
            request_ids.extend(jobs.request_ids)
            jobs = jobs.next  # Move to the next page

        print(f"Successful jobs: {len(request_ids)}", request_ids)

        return request_ids

    def previous_submitted_job_interaction(self):
        remote = client.submit(
            self.collection_id,
            self.request
        )
        remote = client.get_remote(remote.request_id)

        print(
            f"Remote collection id: {remote.collection_id}\n"
            f"Remote request: {remote.request}\n"
            f"Remote status: {remote.status}\n"
            f"Remote results ready: {remote.results_ready}\n"
            f"Remote created at: {remote.created_at}\n"
            f"Remote started at: {remote.started_at}\n"
            f"Remote finished at: {remote.finished_at}\n"
            f"Remote updated at: {remote.updated_at}\n"
        )

        target_4 = remote.download("target_4.grib")
        print(
            f"Remote get receipt: {remote.get_receipt()}\n"
            f"Remote get results: {remote.get_results()}\n"
            )

        return target_4

    def apply_constraints(self):
        month = {
            "year": "2000",
            "month": "02",
        }
        constrained_request = client.apply_constraints(
            self.collection_id,
            month
        )

        print(
            f"The length of the constraints:"
            f"{len(constrained_request['day'])}\n"
        )

        return constrained_request


class CDSAPIClient:
    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key

    def retrieve_data_single(self):
        client = cdsapi.Client(url=self.url, key=self.key)
        dataset = "reanalysis-era5-pressure-levels"
        request = {
            "product_type": ["reanalysis"],
            "variable": ["geopotential"],
            "year": ["2024"],
            "month": ["01"],
            "day": ["01"],
            "time": ["13:00"],
            "pressure_level": ["1000"],
            "format": "grib",
        }

        target = "./download.grib"

        return client.retrieve(dataset, request, target)

    def retrieve_data_bulk(self):
        dataset = "reanalysis-era5-land"
        request = {
            "product_type": ["reanalysis"],
            "variable": [
                "2m_dewpoint_temperature",
                "2m_temperature",
                "snow_albedo",
                "snow_depth",
                "snowfall",
                "forecast_albedo",
                "surface_solar_radiation_downwards",
                "10m_u_component_of_wind",
                "10m_v_component_of_wind",
                "surface_pressure"
            ],
            "year": ["1950"],
            "month": ["01"],
            "day": [
                "01", "02", "03",
                "04", "05", "06",
                "07", "08", "09",
                "10", "11", "12",
                "13", "14", "15",
                "16", "17", "18",
                "19", "20", "21",
                "22", "23", "24",
                "25", "26", "27",
                "28", "29", "30",
                "31"
            ],
            "time": [
                "00:00", "01:00", "02:00",
                "03:00", "04:00", "05:00",
                "06:00", "07:00", "08:00",
                "09:00", "10:00", "11:00",
                "12:00", "13:00", "14:00",
                "15:00", "16:00", "17:00",
                "18:00", "19:00", "20:00",
                "21:00", "22:00", "23:00"
            ],
            "format": "grib",
        }

        target = "./test_download.grib"

        return client.retrieve(dataset, request, target)


if __name__ == "__main__":
    test = CDSAPIClient(url, key)
    test.retrieve_data_bulk()
