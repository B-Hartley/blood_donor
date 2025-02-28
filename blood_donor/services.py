"""Services for Blood Donor integration."""
import logging
import voluptuous as vol
from datetime import datetime, timedelta
import async_timeout
import json

from homeassistant.core import HomeAssistant, ServiceCall, callback
import homeassistant.helpers.config_validation as cv

from . import DOMAIN
from .booking_helper import setup_booking_helper_service

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_AVAILABLE_APPOINTMENTS = "available_appointments"
SERVICE_SESSION_SLOTS = "session_slots"
SERVICE_BOOK_APPOINTMENT = "book_appointment"

SERVICE_SCHEMA_REFRESH = vol.Schema({})

SERVICE_SCHEMA_AVAILABLE_APPOINTMENTS = vol.Schema({
    vol.Required("venue_id"): cv.string,
    vol.Optional("start_date"): cv.date,
    vol.Optional("end_date"): cv.date,
    vol.Optional("procedure_code"): cv.string,
})

SERVICE_SCHEMA_SESSION_SLOTS = vol.Schema({
    vol.Required("session_id"): cv.string,
    vol.Required("session_date"): cv.string,
    vol.Optional("procedure_code"): cv.string,
})

SERVICE_SCHEMA_BOOK_APPOINTMENT = vol.Schema({
    vol.Required("session_id"): cv.string,
    vol.Required("session_date"): cv.string,
    vol.Required("session_time"): cv.string,
    vol.Required("venue_id"): cv.string,
    vol.Optional("procedure_code"): cv.string,
})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Blood Donor integration."""
    _LOGGER.debug("Setting up Blood Donor services")

    # Check if services are already registered
    if (hass.services.has_service(DOMAIN, SERVICE_REFRESH) and 
        hass.services.has_service(DOMAIN, SERVICE_AVAILABLE_APPOINTMENTS) and
        hass.services.has_service(DOMAIN, SERVICE_SESSION_SLOTS) and
        hass.services.has_service(DOMAIN, SERVICE_BOOK_APPOINTMENT)):
        return

    @callback
    async def async_refresh_service(call: ServiceCall) -> None:
        """Refresh Blood Donor data."""
        _LOGGER.debug("Refresh service called")
        coordinators = hass.data.get(DOMAIN, {})
        
        if not coordinators:
            _LOGGER.warning("No Blood Donor coordinators found")
            return
            
        _LOGGER.debug("Found %d coordinators to refresh", len(coordinators))
        
        for entry_id, coordinator in coordinators.items():
            _LOGGER.debug("Refreshing coordinator for entry %s", entry_id)
            await coordinator.async_refresh()
    
    @callback
    async def async_available_appointments_service(call: ServiceCall) -> None:
        """Get available appointments."""
        _LOGGER.debug("Available appointments service called with: %s", call.data)
        
        coordinators = hass.data.get(DOMAIN, {})
        if not coordinators:
            _LOGGER.warning("No Blood Donor coordinators found")
            return
        
        venue_id = call.data.get("venue_id")
        
        # Use provided dates or defaults
        start_date = call.data.get("start_date")
        if start_date is None:
            start_date = datetime.now().date()
        
        end_date = call.data.get("end_date")
        if end_date is None:
            end_date = start_date + timedelta(days=90)  # Default to 90 days from start
        
        procedure_code = call.data.get("procedure_code", "")
        
        # Format dates as strings in the format the API expects
        start_date_str = f"{start_date.isoformat()}T00:00:00"
        end_date_str = f"{end_date.isoformat()}T00:00:00"
        
        _LOGGER.debug("Fetching appointments for venue %s from %s to %s", 
                     venue_id, start_date_str, end_date_str)
        
        # Get the first coordinator (we just need its API for authentication)
        coordinator = next(iter(coordinators.values()))
        
        try:
            # Use the API client from the coordinator to make the request
            if not coordinator.api._access_token:
                await coordinator.api.login()
                
            if not coordinator.api._access_token:
                _LOGGER.error("Failed to login to Blood Donor service")
                return
                
            with async_timeout.timeout(30):
                headers = {"Authorization": f"Bearer {coordinator.api._access_token}"}
                session = coordinator.api._session
                
                # Build the URL with parameters
                url = f"https://my.blood.co.uk/api/sessions/{venue_id}"
                params = {
                    "startDate": start_date_str,
                    "endDate": end_date_str
                }
                
                if procedure_code:
                    params["procedureCode"] = procedure_code
                
                _LOGGER.debug("Making request to %s with params %s", url, params)
                
                response = await session.get(url, headers=headers, params=params)
                
                if response.status == 401:
                    # Token expired, try to login again
                    _LOGGER.debug("Token expired, logging in again")
                    if await coordinator.api.login():
                        return await async_available_appointments_service(call)
                    _LOGGER.error("Re-login failed")
                    return
                
                if response.status != 200:
                    _LOGGER.error("Failed to get available appointments: %s", await response.text())
                    return
                
                data = await response.json()
                sessions = data.get("sessions", [])
                
                available_dates = {}
                session_details = {}
                
                # Process the sessions to find available slots
                for session in sessions:
                    session_id = session.get("sessionId", "")
                    session_date = session.get("sessionDate", "").split("T")[0]
                    session_date_full = session.get("sessionDate", "")
                    periods = session.get("periods", [])
                    
                    total_available = 0
                    period_availability = []
                    
                    for period in periods:
                        available_slots = int(period.get("availableSlots", 0))
                        total_available += available_slots
                        
                        if available_slots > 0:
                            start_time = period.get("startTime", "")
                            end_time = period.get("endTime", "")
                            
                            # Format time nicely
                            start_time_formatted = (f"{start_time[:2]}:{start_time[2:]}" 
                                                 if len(start_time) >= 4 else start_time)
                            end_time_formatted = (f"{end_time[:2]}:{end_time[2:]}" 
                                               if len(end_time) >= 4 else end_time)
                            
                            period_info = {
                                "start_time": start_time_formatted,
                                "end_time": end_time_formatted,
                                "available_slots": available_slots
                            }
                            period_availability.append(period_info)
                    
                    if total_available > 0:
                        available_dates[session_date] = {
                            "total_available": total_available,
                            "periods": period_availability,
                            "session_id": session_id,
                            "session_date_full": session_date_full
                        }
                        
                        # Store session details for later use
                        session_details[session_id] = {
                            "session_date": session_date_full,
                            "total_available": total_available
                        }
                
                # Create persistent notification with the results
                if available_dates:
                    message = "## Available Blood Donation Appointments\n\n"
                    
                    for date, info in sorted(available_dates.items()):
                        message += f"### {date} - {info['total_available']} slots\n"
                        message += f"Session ID: {info['session_id']}\n\n"
                        
                        for period in info["periods"]:
                            message += f"- {period['start_time']} to {period['end_time']}: {period['available_slots']} slots\n"
                        
                        message += "\nTo see detailed slot times, call the service with:\n"
                        message += f"```yaml\nservice: blood_donor.session_slots\ndata:\n  session_id: \"{info['session_id']}\"\n  session_date: \"{info['session_date_full']}\"\n```\n\n"
                else:
                    message = "No available appointments found for the selected date range."
                
                # Store session details in Home Assistant for later reference
                hass.data.setdefault(f"{DOMAIN}_sessions", {}).update(session_details)
                
                hass.components.persistent_notification.async_create(
                    message,
                    title="Blood Donor Available Appointments",
                    notification_id=f"blood_donor_appointments_{venue_id}"
                )
                
                _LOGGER.debug("Created notification with available appointments")
                
        except Exception as error:
            _LOGGER.exception("Error fetching available appointments: %s", error)

    @callback
    async def async_session_slots_service(call: ServiceCall) -> None:
        """Get detailed slot information for a specific session."""
        _LOGGER.debug("Session slots service called with: %s", call.data)
        
        coordinators = hass.data.get(DOMAIN, {})
        if not coordinators:
            _LOGGER.warning("No Blood Donor coordinators found")
            return
        
        session_id = call.data.get("session_id")
        session_date = call.data.get("session_date")
        procedure_code = call.data.get("procedure_code", "")
        
        _LOGGER.debug("Fetching slot details for session %s on %s", session_id, session_date)
        
        # Get the first coordinator (we just need its API for authentication)
        coordinator = next(iter(coordinators.values()))
        
        try:
            # Use the API client from the coordinator to make the request
            if not coordinator.api._access_token:
                await coordinator.api.login()
                
            if not coordinator.api._access_token:
                _LOGGER.error("Failed to login to Blood Donor service")
                return
                
            with async_timeout.timeout(30):
                headers = {"Authorization": f"Bearer {coordinator.api._access_token}"}
                session_obj = coordinator.api._session
                
                # Build the URL with parameters
                url = f"https://my.blood.co.uk/api/appointments/{session_id}/slots"
                params = {
                    "sessionDate": session_date
                }
                
                if procedure_code:
                    params["procedureCode"] = procedure_code
                
                _LOGGER.debug("Making request to %s with params %s", url, params)
                
                response = await session_obj.get(url, headers=headers, params=params)
                
                if response.status == 401:
                    # Token expired, try to login again
                    _LOGGER.debug("Token expired, logging in again")
                    if await coordinator.api.login():
                        return await async_session_slots_service(call)
                    _LOGGER.error("Re-login failed")
                    return
                
                if response.status != 200:
                    _LOGGER.error("Failed to get session slots: %s", await response.text())
                    return
                
                data = await response.json()
                _LOGGER.debug("Got slot data: %s", data)
                
                slots = data.get("slots", [])
                
                # Create persistent notification with the results
                if slots:
                    message = f"## Available Slots for Session {session_id}\n\n"
                    message += f"Date: {session_date.split('T')[0]}\n\n"
                    
                    for slot in slots:
                        time_str = slot.get("time", "").replace("T", "")
                        time_formatted = f"{time_str[:2]}:{time_str[2:]}" if len(time_str) >= 4 else time_str
                        procedure = slot.get("procedureDescription", "")
                        last_one = slot.get("lastOneAvailable", False)
                        procedure_code_value = slot.get("procedureCode", "")
                        
                        message += f"- **{time_formatted}** - {procedure}"
                        if last_one:
                            message += " (Last available slot!)"
                        
                        # Add booking service call example
                        message += f"\n  ```yaml\n  service: blood_donor.book_appointment\n  data:\n    session_id: \"{session_id}\"\n    session_date: \"{session_date}\"\n    session_time: \"T{time_str}\"\n    venue_id: \"{call.data.get('venue_id', 'TB78A')}\"\n    procedure_code: \"{procedure_code_value}\"\n  ```\n"
                        
                else:
                    message = "No available slots found for this session."
                
                hass.components.persistent_notification.async_create(
                    message,
                    title=f"Blood Donor Appointment Slots - {session_date.split('T')[0]}",
                    notification_id=f"blood_donor_slots_{session_id}"
                )
                
                _LOGGER.debug("Created notification with session slots")
                
        except Exception as error:
            _LOGGER.exception("Error fetching session slots: %s", error)

    @callback
    async def async_book_appointment_service(call: ServiceCall) -> None:
        """Book a blood donation appointment."""
        _LOGGER.debug("Book appointment service called with: %s", call.data)
        
        coordinators = hass.data.get(DOMAIN, {})
        if not coordinators:
            _LOGGER.warning("No Blood Donor coordinators found")
            return
        
        session_id = call.data.get("session_id")
        session_date = call.data.get("session_date")
        session_time = call.data.get("session_time")
        venue_id = call.data.get("venue_id")
        procedure_code = call.data.get("procedure_code", "")
        
        _LOGGER.debug("Booking appointment for session %s on %s at %s", 
                     session_id, session_date, session_time)
        
        # Get the first coordinator (we just need its API for authentication)
        coordinator = next(iter(coordinators.values()))
        
        try:
            # Use the API client from the coordinator to make the request
            if not coordinator.api._access_token:
                await coordinator.api.login()
                
            if not coordinator.api._access_token:
                _LOGGER.error("Failed to login to Blood Donor service")
                return
                
            with async_timeout.timeout(30):
                headers = {
                    "Authorization": f"Bearer {coordinator.api._access_token}",
                    "Content-Type": "application/json"
                }
                session_obj = coordinator.api._session
                
                # Build the request payload
                payload = {
                    "sessionID": session_id,
                    "sessionDate": session_date,
                    "sessionTime": session_time,
                    "venueId": venue_id,
                    "procedureCode": procedure_code,
                    "platform": "web"
                }
                
                _LOGGER.debug("Making request to book appointment with payload: %s", payload)
                
                response = await session_obj.post(
                    "https://my.blood.co.uk/api/appointments/book",
                    headers=headers,
                    json=payload
                )
                
                if response.status == 401:
                    # Token expired, try to login again
                    _LOGGER.debug("Token expired, logging in again")
                    if await coordinator.api.login():
                        return await async_book_appointment_service(call)
                    _LOGGER.error("Re-login failed")
                    return
                
                response_text = await response.text()
                _LOGGER.debug("Book appointment response: %s", response_text)
                
                if response.status != 200:
                    _LOGGER.error("Failed to book appointment: %s", response_text)
                    hass.components.persistent_notification.async_create(
                        f"Failed to book appointment: {response_text}",
                        title="Blood Donor Appointment Booking Failed",
                        notification_id="blood_donor_booking_failed"
                    )
                    return
                
                # Parse the response
                try:
                    data = await response.json()
                    
                    # Get appointment details
                    status = data.get("status", "")
                    time = data.get("time", "").replace("T", "")
                    time_formatted = f"{time[:2]}:{time[2:]}" if len(time) >= 4 else time
                    procedure = data.get("procedureDescription", "")
                    venue_name = data.get("session", {}).get("venue", {}).get("venueName", "")
                    
                    appointment_date = session_date.split("T")[0]
                    
                    # Format a success message
                    if status == "B":
                        message = f"## Appointment Booked Successfully!\n\n"
                        message += f"**Date:** {appointment_date}\n"
                        message += f"**Time:** {time_formatted}\n"
                        message += f"**Venue:** {venue_name}\n"
                        message += f"**Procedure:** {procedure}\n\n"
                        message += "Your appointment has been booked. Remember to prepare accordingly."
                        
                        hass.components.persistent_notification.async_create(
                            message,
                            title="Blood Donor Appointment Booked",
                            notification_id="blood_donor_booking_success"
                        )
                        
                        # Also trigger a refresh to update all entities with the new appointment
                        await coordinator.async_refresh()
                        
                    else:
                        hass.components.persistent_notification.async_create(
                            f"Appointment booking returned status: {status}. Please check the Blood Donor website for details.",
                            title="Blood Donor Appointment Booking Status",
                            notification_id="blood_donor_booking_status"
                        )
                
                except json.JSONDecodeError:
                    _LOGGER.error("Failed to parse booking response")
                    hass.components.persistent_notification.async_create(
                        "Failed to parse the booking response. Please check the Blood Donor website to verify if the appointment was booked.",
                        title="Blood Donor Appointment Booking Error",
                        notification_id="blood_donor_booking_error"
                    )
                
        except Exception as error:
            _LOGGER.exception("Error booking appointment: %s", error)
            hass.components.persistent_notification.async_create(
                f"An error occurred while booking your appointment: {str(error)}",
                title="Blood Donor Appointment Booking Error",
                notification_id="blood_donor_booking_error"
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        async_refresh_service,
        schema=SERVICE_SCHEMA_REFRESH,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_AVAILABLE_APPOINTMENTS,
        async_available_appointments_service,
        schema=SERVICE_SCHEMA_AVAILABLE_APPOINTMENTS,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_SESSION_SLOTS,
        async_session_slots_service,
        schema=SERVICE_SCHEMA_SESSION_SLOTS,
    )
    
    hass.services.async_register(
        DOMAIN, 
        SERVICE_BOOK_APPOINTMENT,
        async_book_appointment_service,
        schema=SERVICE_SCHEMA_BOOK_APPOINTMENT,
    )
    
    await setup_booking_helper_service(hass)
    
    _LOGGER.debug("Blood Donor services registered")