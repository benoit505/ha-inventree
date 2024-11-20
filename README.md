# Home Assistant InvenTree Integration

A Home Assistant integration for InvenTree inventory management system.
Features

Fetches stock levels from InvenTree categories
Creates sensors for inventory tracking
Allows stock adjustments directly from Home Assistant
Integrates with custom Lovelace cards for visualization

Installation
HACS (Recommended)

Make sure you have HACS installed
Add this repository as a custom repository in HACS:

Click on HACS in your Home Assistant instance
Click on the three dots in the top right corner
Click on Custom repositories
Add https://github.com/benoit505/ha-inventree as an Integration


Search for "InvenTree" in HACS and install

Manual Installation

Copy the custom_components/inventree directory to your Home Assistant's custom_components directory
Restart Home Assistant

Configuration
Add your InvenTree credentials through the UI:

Go to Configuration > Integrations
Click the + button
Search for "InvenTree"
Follow the configuration steps

Usage
After configuration, the integration will create sensors for each InvenTree category.
Example automation:
yamlCopyautomation:
  - alias: "Low Stock Alert"
    trigger:
      platform: numeric_state
      entity_id: sensor.inventree_category_stock
      below: 5
    action:
      - service: notify.notify
        data:
          message: "Stock is running low!"
Contributing
Feel free to contribute! Just open a PR.
