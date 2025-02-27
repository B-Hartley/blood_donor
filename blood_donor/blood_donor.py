"""
Blood Donor integration for Home Assistant.
For more details about this integration, please refer to the documentation.
"""
import asyncio
import logging
from datetime import datetime, timedelta
import voluptuous as vol

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "blood_donor"
SCAN_INTERVAL = timedelta(hours=12)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = ["sensor"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Blood Donor component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Blood Donor from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    api = BloodDonorApi(session, username, password)

    coordinator = BloodDonorDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up services
    from .services import async_setup_services
    await async_setup_services(hass)

    # Set up sensor platform - which now includes the award sensors
    await hass.config_entries.async_forward_entry_setup(entry, "sensor")
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class BloodDonorApi:
    """API client for Blood Donor."""

    def __init__(self, session, username, password):
        """Initialize the API client."""
        self._session = session
        self._username = username
        self._password = password
        self._access_token = None
        self._refresh_token = None
        self._donor_id = None

    async def login(self):
        """Login to the Blood Donor service."""
        _LOGGER.debug("Attempting to login to Blood Donor service with username: %s", self._username)
        try:
            with async_timeout.timeout(10):
                _LOGGER.debug("Sending login request to Blood Donor API")
                response = await self._session.post(
                    "https://my.blood.co.uk/api/auth/v2/login",
                    json={
                        "username": self._username,
                        "password": self._password,
                        "platform": "web",
                        "plasmaLoginAllowed": True,
                    },
                )
                _LOGGER.debug("Login response status: %s", response.status)
                
                # Log the first part of the response for debugging
                response_text = await response.text()
                _LOGGER.debug("Login response preview: %s", response_text[:200] + "..." if len(response_text) > 200 else response_text)
                
                try:
                    data = await response.json()
                except ValueError:
                    _LOGGER.error("Failed to parse login response as JSON. Response: %s", response_text[:500])
                    return False
                
                if response.status != 200:
                    _LOGGER.error("Failed to login: %s", data)
                    return False
                
                self._access_token = data.get("accessToken")
                self._refresh_token = data.get("refreshToken")
                
                # In the login response, accountDetails is a field in the response
                if "accountDetails" in data:
                    self._donor_id = data.get("accountDetails", {}).get("donorID")
                    _LOGGER.debug("Successfully logged in with donor ID: %s", self._donor_id)
                else:
                    _LOGGER.error("Login succeeded but accountDetails not found in login response")
                    _LOGGER.debug("Response keys: %s", list(data.keys()))
                
                _LOGGER.debug("Login successful")
                return True
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while connecting to Blood Donor service")
            return False
        except (aiohttp.ClientError, ValueError) as error:
            _LOGGER.error("Error connecting to Blood Donor service: %s", error)
            return False

    async def get_data(self):
        """Get data from the Blood Donor service."""
        _LOGGER.debug("Fetching data from Blood Donor service")
        
        if not self._access_token:
            _LOGGER.debug("No access token available, attempting to login")
            if not await self.login():
                _LOGGER.error("Failed to login, cannot fetch data")
                return None

        try:
            account_data = await self._get_account_details()
            if not account_data:
                return None
                
            # Get awards data
            awards_data = await self._get_awards()
            if awards_data:
                account_data["awards"] = awards_data
                
            return account_data
                
        except Exception as exception:
            _LOGGER.exception("Unexpected error during data update")
            raise UpdateFailed(f"Error communicating with API: {exception}")

    async def _get_account_details(self):
        """Get account details from the Blood Donor service."""
        try:
            with async_timeout.timeout(10):
                _LOGGER.debug("Sending request for account details with token: %s...", 
                             self._access_token[:10] if self._access_token else "None")
                
                headers = {"Authorization": f"Bearer {self._access_token}"}
                response = await self._session.get(
                    "https://my.blood.co.uk/api/account/v2/details",
                    headers=headers,
                )
                _LOGGER.debug("Account details response status: %s", response.status)
                
                response_text = await response.text()
                _LOGGER.debug("Account details response preview: %s", 
                             response_text[:200] + "..." if len(response_text) > 200 else response_text)
                
                if response.status == 401:
                    _LOGGER.debug("Token expired (401), attempting to login again")
                    if await self.login():
                        _LOGGER.debug("Re-login successful, retrying data fetch")
                        return await self._get_account_details()
                    _LOGGER.error("Re-login failed, cannot fetch data")
                    return None
                
                if response.status != 200:
                    _LOGGER.error("Failed to get account details: %s", response_text)
                    return None
                
                try:
                    data = await response.json()
                    _LOGGER.debug("Successfully parsed account details data")
                    
                    # For the account details endpoint, the data is at the root level
                    # No need to look for an accountDetails object
                    if "appointments" in data:
                        _LOGGER.debug("Found appointments in response")
                        _LOGGER.debug("Found %d appointments", len(data.get("appointments", [])))
                    else:
                        _LOGGER.warning("appointments not found in API response")
                        _LOGGER.debug("Response keys: %s", list(data.keys()))
                    
                    return data
                except ValueError:
                    _LOGGER.error("Failed to parse account details response as JSON: %s", response_text[:500])
                    return None
                    
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while fetching account data from Blood Donor service")
            return None
        except (aiohttp.ClientError, ValueError) as error:
            _LOGGER.error("Error fetching account data from Blood Donor service: %s", error)
            return None

    async def _get_awards(self):
        """Get awards data from the Blood Donor service."""
        try:
            with async_timeout.timeout(10):
                _LOGGER.debug("Sending request for awards data")
                
                headers = {"Authorization": f"Bearer {self._access_token}"}
                response = await self._session.get(
                    "https://my.blood.co.uk/api/account/awards",
                    headers=headers,
                )
                _LOGGER.debug("Awards response status: %s", response.status)
                
                response_text = await response.text()
                _LOGGER.debug("Awards response preview: %s", 
                             response_text[:200] + "..." if len(response_text) > 200 else response_text)
                
                if response.status == 401:
                    _LOGGER.debug("Token expired (401), attempting to login again")
                    if await self.login():
                        _LOGGER.debug("Re-login successful, retrying awards fetch")
                        return await self._get_awards()
                    _LOGGER.error("Re-login failed, cannot fetch awards data")
                    return None
                
                if response.status != 200:
                    _LOGGER.error("Failed to get awards data: %s", response_text)
                    return None
                
                try:
                    data = await response.json()
                    _LOGGER.debug("Successfully parsed awards data: %s", data)
                    return data
                except ValueError:
                    _LOGGER.error("Failed to parse awards response as JSON: %s", response_text[:500])
                    return None
                    
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while fetching awards data from Blood Donor service")
            return None
        except (aiohttp.ClientError, ValueError) as error:
            _LOGGER.error("Error fetching awards data from Blood Donor service: %s", error)
            return None


class BloodDonorDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass, api):
        """Initialize."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        _LOGGER.debug("Blood Donor coordinator initialized")

    async def _async_update_data(self):
        """Update data via API."""
        _LOGGER.debug("Coordinator updating data from Blood Donor API")
        try:
            data = await self.api.get_data()
            if not data:
                _LOGGER.error("API get_data() returned None")
                raise UpdateFailed("Failed to fetch data from Blood Donor service")
            
            _LOGGER.debug("Coordinator received data from API with keys: %s", list(data.keys()))
            
            # Check if awards data was successfully retrieved
            if "awards" in data:
                _LOGGER.debug("Awards data found in API response")
            
            return data
        except Exception as exception:
            _LOGGER.exception("Unexpected error during data update")
            raise UpdateFailed(f"Error communicating with API: {exception}")