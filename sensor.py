"""Platform for Blood Donor sensor integration."""
import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, BloodDonorDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blood Donor sensor based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        BloodDonorNextAppointmentSensor(coordinator),
        BloodDonorDonationCreditSensor(coordinator),
        BloodDonorBloodGroupSensor(coordinator),
        BloodDonorTotalAppointmentsSensor(coordinator),
        # Add award sensors
        BloodDonorAwardStateSensor(coordinator),
        BloodDonorTotalCreditsSensor(coordinator),
        BloodDonorTotalAwardsSensor(coordinator),
        BloodDonorRegistrationDateSensor(coordinator),
        BloodDonorNextMilestoneSensor(coordinator),
    ]

    async_add_entities(sensors, True)


class BloodDonorBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Blood Donor sensors."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.api._donor_id)},
            "name": "Blood Donor",
            "manufacturer": "Blood.co.uk",
        }

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class BloodDonorNextAppointmentSensor(BloodDonorBaseSensor):
    """Sensor for the next blood donation appointment."""

    _attr_name = "Next Appointment"
    _attr_icon = "mdi:calendar-clock"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_next_appointment"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data available for next appointment sensor")
            return None

        _LOGGER.debug("Coordinator data keys: %s", list(self.coordinator.data.keys()))
        
        # Data is directly at the root level, not under accountDetails
        appointments = self.coordinator.data.get("appointments", [])
        _LOGGER.debug("Found %d appointments in data", len(appointments))
        
        if not appointments:
            _LOGGER.debug("No appointments found in data")
            return "No appointments scheduled"

        # Sort appointments by date
        try:
            sorted_appointments = sorted(
                appointments,
                key=lambda x: datetime.strptime(
                    x["session"]["sessionDate"].split("T")[0], "%Y-%m-%d"
                ),
            )
            
            _LOGGER.debug("Sorted %d appointments", len(sorted_appointments))
            next_appointment = sorted_appointments[0]
            _LOGGER.debug("Next appointment session date: %s", next_appointment["session"]["sessionDate"])
            
            appointment_date = datetime.strptime(
                next_appointment["session"]["sessionDate"].split("T")[0], "%Y-%m-%d"
            ).strftime("%Y-%m-%d")
            
            _LOGGER.debug("Next appointment formatted date: %s", appointment_date)
            return appointment_date
            
        except (KeyError, ValueError, IndexError) as error:
            _LOGGER.error("Error processing appointment data: %s", error)
            if appointments:
                _LOGGER.debug("First appointment data: %s", appointments[0])
            return None

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}

        # Data is directly at the root level, not under accountDetails
        appointments = self.coordinator.data.get("appointments", [])
        if not appointments:
            return {"appointments": []}

        # Sort appointments by date
        sorted_appointments = sorted(
            appointments,
            key=lambda x: datetime.strptime(
                x["session"]["sessionDate"].split("T")[0], "%Y-%m-%d"
            ),
        )

        next_appointment = sorted_appointments[0]
        venue = next_appointment["session"]["venue"]["venueName"]
        time = next_appointment["time"].replace("T", "")
        procedure = next_appointment["procedureDescription"]
        
        # Format time from 24-hour format (e.g., 1255) to 12-hour format with AM/PM
        time_formatted = f"{int(time[:2])}:{time[2:]} {'AM' if int(time[:2]) < 12 else 'PM'}"
        if int(time[:2]) > 12:
            time_formatted = f"{int(time[:2]) - 12}:{time[2:]} PM"
            
        address = ", ".join(
            [line.strip() for line in next_appointment["session"]["venue"]["address"]["lines"]]
        )
        postcode = next_appointment["session"]["venue"]["address"]["postcode"].strip()

        return {
            "venue": venue,
            "time": time_formatted,
            "procedure": procedure,
            "address": address,
            "postcode": postcode,
            "all_appointments": [
                {
                    "date": datetime.strptime(
                        apt["session"]["sessionDate"].split("T")[0], "%Y-%m-%d"
                    ).strftime("%Y-%m-%d"),
                    "time": apt["time"].replace("T", ""),
                    "venue": apt["session"]["venue"]["venueName"],
                    "procedure": apt["procedureDescription"],
                }
                for apt in sorted_appointments
            ],
        }


class BloodDonorDonationCreditSensor(BloodDonorBaseSensor):
    """Sensor for the donation credit."""

    _attr_name = "Donation Credit"
    _attr_icon = "mdi:counter"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_donation_credit"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        # Data is directly at the root level, not under accountDetails
        return self.coordinator.data.get("donationCredit")

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "donations"


class BloodDonorBloodGroupSensor(BloodDonorBaseSensor):
    """Sensor for blood group."""

    _attr_name = "Blood Group"
    _attr_icon = "mdi:water"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_blood_group"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        # Data is directly at the root level, not under accountDetails
        return self.coordinator.data.get("bloodGroup")


class BloodDonorTotalAppointmentsSensor(BloodDonorBaseSensor):
    """Sensor for total upcoming appointments."""

    _attr_name = "Total Upcoming Appointments"
    _attr_icon = "mdi:calendar-multiple"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_total_appointments"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        # Data is directly at the root level, not under accountDetails
        appointments = self.coordinator.data.get("appointments", [])
        return len(appointments)
        
class BloodDonorAwardBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Blood Donor award sensors."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.api._donor_id)},
            "name": "Blood Donor",
            "manufacturer": "Blood.co.uk",
        }

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class BloodDonorAwardStateSensor(BloodDonorAwardBaseSensor):
    """Sensor for the current award state."""

    _attr_name = "Award State"
    _attr_icon = "mdi:trophy"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_award_state"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            _LOGGER.debug("No coordinator award data available")
            return None

        return self.coordinator.data.get("awards", {}).get("awardState", "Unknown")

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return {}

        awards_data = self.coordinator.data.get("awards", {})
        achieved_awards = []
        
        for award in awards_data.get("awards", []):
            if award.get("isAchieved", False):
                awarded_date = award.get("awardedDate")
                if awarded_date:
                    try:
                        date_obj = datetime.strptime(awarded_date.split("T")[0], "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%d %b %Y")
                    except (ValueError, TypeError):
                        formatted_date = None
                else:
                    formatted_date = None
                
                achieved_awards.append({
                    "title": award.get("title"),
                    "credit_criteria": award.get("creditCriteria"),
                    "awarded_date": formatted_date
                })
        
        # Sort by credit criteria (descending)
        achieved_awards.sort(key=lambda x: x["credit_criteria"], reverse=True)
        
        return {
            "show_as_achievement": awards_data.get("showAsAchievement", False),
            "achieved_awards": achieved_awards,
        }


class BloodDonorTotalCreditsSensor(BloodDonorAwardBaseSensor):
    """Sensor for total donation credits."""

    _attr_name = "Total Credits"
    _attr_icon = "mdi:counter"
    _attr_unit_of_measurement = "credits"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_total_credits"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return None

        return self.coordinator.data.get("awards", {}).get("totalCredits", 0)


class BloodDonorTotalAwardsSensor(BloodDonorAwardBaseSensor):
    """Sensor for total awards received."""

    _attr_name = "Total Awards"
    _attr_icon = "mdi:medal"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_total_awards"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return None

        return self.coordinator.data.get("awards", {}).get("totalAwards", 0)


class BloodDonorRegistrationDateSensor(BloodDonorAwardBaseSensor):
    """Sensor for donor registration date."""

    _attr_name = "Registration Date"
    _attr_icon = "mdi:calendar-clock"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_registration_date"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return None

        registration_date = self.coordinator.data.get("awards", {}).get("registrationDate")
        if registration_date:
            try:
                date_obj = datetime.strptime(registration_date.split("T")[0], "%Y-%m-%d")
                return date_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                return None
        return None


class BloodDonorNextMilestoneSensor(BloodDonorAwardBaseSensor):
    """Sensor for next milestone."""

    _attr_name = "Next Milestone"
    _attr_icon = "mdi:flag-checkered"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.coordinator.api._donor_id}_next_milestone"

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return None

        awards_data = self.coordinator.data.get("awards", {})
        awards_list = awards_data.get("awards", [])
        
        # Find the first non-achieved award
        for award in awards_list:
            if not award.get("isAchieved", True):
                return award.get("title", "Unknown")
                
        return "All milestones achieved"
        
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data or "awards" not in self.coordinator.data:
            return {}

        awards_data = self.coordinator.data.get("awards", {})
        total_credits = awards_data.get("totalCredits", 0)
        
        # Find the next milestone and calculate progress
        next_milestone = None
        progress = 0
        
        for award in awards_data.get("awards", []):
            if not award.get("isAchieved", True):
                next_milestone = award
                break
                
        if next_milestone:
            milestone_credits = next_milestone.get("creditCriteria", 0)
            if milestone_credits > 0:
                progress = min(100, round(total_credits / milestone_credits * 100))
                credits_needed = milestone_credits - total_credits
            else:
                progress = 0
                credits_needed = 0
                
            return {
                "next_milestone_credits": milestone_credits,
                "credits_needed": credits_needed,
                "progress_percentage": progress
            }
            
        return {
            "next_milestone_credits": None,
            "credits_needed": 0,
            "progress_percentage": 100
        }        