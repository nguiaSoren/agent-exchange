"""Band Agent API — client interface, in-memory fake, real HTTP impl, consent flow."""

from .client import BandClient, BandWorld, FakeBandClient
from .consent import auto_approve_requests, establish_contact, mutual_link
from .http_client import HttpBandClient, make_http_band_client, specialist_band_keys

__all__ = ["BandClient", "FakeBandClient", "BandWorld",
           "HttpBandClient", "make_http_band_client", "specialist_band_keys",
           "establish_contact", "auto_approve_requests", "mutual_link"]
