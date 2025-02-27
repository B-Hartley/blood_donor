This is very much a work in progress.............
comments to:
https://community.home-assistant.io/t/uk-blood-donation-custom-component/854704

# Blood Donor Integration for Home Assistant

This custom integration allows you to monitor your blood donation appointments and donor details from the UK's Blood Donor service in Home Assistant, as well as check for available appointments and book new ones.

## Features

- View your next scheduled appointment with date, time, and location
- See all upcoming appointments
- Monitor your donation credit count
- Display your blood group
- Track the total number of scheduled appointments
- Check for available appointment slots at donation centers
- View detailed time slots for specific sessions
- Book new appointments directly from Home Assistant

## Installation

### HACS (Home Assistant Community Store)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Add this repository as a custom repository in HACS:
   - Go to HACS > Integrations
   - Click the three dots in the upper right corner
   - Select "Custom repositories"
   - Add the URL of this repository
   - Category: Integration
   - Click "Add"
3. Search for "Blood Donor" in HACS and install it
4. Restart Home Assistant

### Manual Installation

1. Copy the `blood_donor` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Configuration > Integrations
2. Click the "+ Add Integration" button
3. Search for "Blood Donor"
4. Enter your Blood Donor login credentials (email and password)

## Available Entities

After setting up the integration, the following entities will be created:

| Entity | Description |
|--------|-------------|
| `sensor.blood_donor_next_appointment` | Your next scheduled appointment date |
| `sensor.blood_donor_donation_credit` | Your donation credit count |
| `sensor.blood_donor_blood_group` | Your blood group |
| `sensor.blood_donor_total_upcoming_appointments` | Total number of scheduled appointments |

## Services

The integration provides several services to interact with the Blood Donor website:

| Service | Description |
|---------|-------------|
| `blood_donor.refresh` | Refresh data from the Blood Donor service |
| `blood_donor.available_appointments` | Check for available appointment slots at a donation venue |
| `blood_donor.session_slots` | Get detailed time slots for a specific session |
| `blood_donor.book_appointment` | Book a new blood donation appointment |

### Checking Available Appointments

To check for available appointments at a donation venue:

```yaml
service: blood_donor.available_appointments
data:
  venue_id: "TB78A"  # Bristol Donor Centre
  start_date: "2025-03-01"
  end_date: "2025-06-01"
  procedure_code: "PLT"  # Optional - for platelet donations
```

This will create a notification showing available dates with their time periods.

### Viewing Detailed Slot Times

Once you find an available date, you can check the specific time slots:

```yaml
service: blood_donor.session_slots
data:
  session_id: "CS3XZG"  # From the available appointments notification
  session_date: "2025-03-05T00:00:00"  # From the available appointments notification
```

This will show you the exact appointment times available for booking.

### Booking an Appointment

After finding an available slot, you can book it directly:

```yaml
service: blood_donor.book_appointment
data:
  session_id: "CS3XZG"
  session_date: "2025-03-05T00:00:00"
  session_time: "T0820"
  venue_id: "TB78A"
  procedure_code: "PLT"  # Optional
```

## Attributes

The `sensor.blood_donor_next_appointment` entity includes the following attributes:

- `venue`: The name of the donation venue
- `time`: The appointment time (in 12-hour format)
- `procedure`: The type of donation (e.g., Whole Blood, Platelet)
- `address`: The full address of the venue
- `postcode`: The postcode of the venue
- `all_appointments`: A list of all upcoming appointments with date, time, venue, and procedure

## Common Venue IDs

| Venue ID | Location |
|----------|----------|
| TB78A | Bristol Donor Centre |
| CV0CI | Reading Donor Centre |

## Automation Examples

### Weekly Check for Available Appointments

```yaml
automation:
  - alias: "Check Blood Donor Appointments Weekly"
    trigger:
      platform: time
      at: "08:00:00"
    condition:
      condition: time
      weekday:
        - mon
    action:
      service: blood_donor.available_appointments
      data:
        venue_id: "TB78A"
        start_date: "{{ now().date() }}"
        end_date: "{{ (now() + timedelta(days=90)).date() }}"
```

## Disclaimer

This integration is not officially affiliated with or endorsed by the NHS Blood and Transplant service. Use at your own risk.

## Support

If you encounter any issues or have questions, please open an issue on the GitHub repository.


# Enhanced Blood Donor Booking Helper

The Booking Helper service has been enhanced with a day-of-week option, making it even more flexible for scheduling your blood donations. Now you can specify either a specific date or your preferred day of the week.

## Using the Day of Week Feature

Instead of picking a specific date, you can now tell the system that you prefer to donate on a particular day of the week, for example, "I prefer to donate on Wednesdays." The system will automatically find the next eligible Wednesday for you to donate.

### Basic Usage with Day of Week

```yaml
service: blood_donor.booking_helper
data:
  venue_id: "TB78A"
  target_day_of_week: "wednesday"  # Instead of target_date
  target_time: "13:00"
  tolerance_hours: 2
  min_days_from_last_appointment: 14
  procedure_code: "PLT"
  auto_book: false
```

This will:
1. Find the next Wednesday that is at least 14 days after your last appointment
2. Look for available slots on that date within 2 hours of 1:00 PM
3. Show you the best match

### How It Works

The service analyzes:
- Your donation history to find your last appointment
- The minimum required days between donations (default: 14 days)
- Your preferred day of the week
- Your preferred time of day

Then it calculates the next eligible date that matches your preferred day of the week and checks for available appointments.

## Example Scenarios

### Scenario 1: Finding the Next Wednesday Appointment

```yaml
service: blood_donor.booking_helper
data:
  venue_id: "TB78A"
  target_day_of_week: "wednesday"
  target_time: "13:00"
  auto_book: false
```

### Scenario 2: Auto-Booking a Weekend Appointment

```yaml
service: blood_donor.booking_helper
data:
  venue_id: "TB78A"
  target_day_of_week: "saturday"
  target_time: "10:00"
  tolerance_hours: 3
  min_days_from_last_appointment: 21  # Ensure 3 weeks since last donation
  auto_book: true
```

## Service Parameters Explained

| Parameter | Description |
|-----------|-------------|
| `venue_id` | The ID of the donation venue (e.g., "TB78A" for Bristol) |
| `target_date` | A specific date for your appointment (use either this OR target_day_of_week) |
| `target_day_of_week` | Your preferred day of the week (monday, tuesday, etc.) |
| `target_time` | Your preferred time of day (HH:MM format) |
| `tolerance_hours` | How many hours before/after your target time is acceptable |
| `min_days_from_last_appointment` | Minimum number of days to ensure between appointments |
| `procedure_code` | The type of donation (PLT for platelet, WB for whole blood, etc.) |
| `auto_book` | Whether to automatically book the best available appointment |

## Automation Examples

### Weekly Check for Saturday Morning Appointments

```yaml
automation:
  - alias: "Check for Weekend Blood Donation Slots"
    trigger:
      platform: time
      at: "07:00:00"
    condition:
      condition: time
      weekday:
        - mon
```


# Blood Donor Milestones and Awards

The integration now includes support for tracking your blood donation milestones and awards!

## Award Sensors

After setting up the integration, the following new award-related entities will be created:

| Entity | Description |
|--------|-------------|
| `sensor.blood_donor_award_state` | Your current award level (e.g., "250 Credits") |
| `sensor.blood_donor_total_credits` | Total donation credits accumulated |
| `sensor.blood_donor_total_awards` | Number of donation awards received |
| `sensor.blood_donor_registration_date` | Date you registered as a blood donor |
| `sensor.blood_donor_next_milestone` | Your next award milestone |

## Award Attributes

The `sensor.blood_donor_award_state` entity includes the following attributes:

- `show_as_achievement`: Whether to show the award as an achievement
- `achieved_awards`: A list of all awards achieved with title, credit criteria, and awarded date

The `sensor.blood_donor_next_milestone` entity includes:

- `next_milestone_credits`: The credit requirement for your next milestone
- `credits_needed`: How many more credits needed to reach the next milestone
- `progress_percentage`: Your progress toward the next milestone as a percentage

## Lovelace Card

You can use the `donor_awards_card.yaml` configuration to create a beautiful dashboard card displaying your award progress. This card requires:

1. The [Mushroom](https://github.com/piitaya/lovelace-mushroom) card collection
2. The [Bar Card](https://github.com/custom-cards/bar-card) custom card

### Example Visualization

The awards card shows:
- Your current award state
- Total credits and awards received
- Registration date
- Progress bar to your next milestone
- List of all achieved awards with dates

### Installation

1. Copy the `donor_awards_card.yaml` file to your Lovelace configuration
2. Add it as a card to your dashboard:

```yaml
type: custom:vertical-stack-card
cards:
  !include donor_awards_card.yaml
```

## Badge Images

For the best experience, create a folder called `blood_donor` in your Home Assistant's `www` folder and add a `donor_badges.png` image showing the badge designs.
