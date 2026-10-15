# Development Plan

## Current Focus: Finish the Dashboard Layout

Finish the layout and usability of Overview, Devices, and Activity before starting
another monitoring feature. Review spacing, empty and populated states, responsive
layouts, navigation, and the existing account and device-management flows.

Implemented polish includes distinct dismissible notifications, a steady background
refresh indicator, mobile inventory cards with accessible management actions,
URL-persisted filters and pagination, the ghost favicon, actionable empty states,
and keyboard-focus restoration. Optional browser regression checks live in
`tests/browser/`; see the README's Testing section for commands.

The account-management gap is closed with `/account` for profile/password changes
and owner-only `/users` for admin creation, renaming, activation, password resets,
and confirmed deletion. Browser CI covers these flows alongside the existing pages.
The existing dashboard layout is retained, with only the required navigation and
page-specific controls added. Remaining dashboard limitations are listed in the README.

Optional named-port monitoring is agreed future work. It is deferred while the
dashboard layout is being finished.

## Deferred: Optional Named-Port Monitoring

### Device and Service Configuration

- Keep device name and host/IP as the basic configuration. A device with only an
  IP address or hostname remains valid and uses the existing ping monitoring.
- Allow zero or more named services per device; ports are optional.
- Provide an **Add monitored port** action in the device form. Each entry contains:
  - A required service name, such as `Home Assistant` or `Admin Dashboard`.
  - A required TCP port from `1` to `65535`.
  - A link type: HTTP, HTTPS, or no browser link.
- Allow services to be added, edited, or removed later from device management.
- Reuse the device's host for all of its services. Reject duplicate ports on the
  same device, while allowing the same port on different devices.
- Support `IP:port` as an input convenience by splitting it into separate host and
  service-port values, then requesting the service name and link type. Require
  bracket notation for IPv6 with an attached port, such as `[::1]:8080`, rather
  than interpreting a bare IPv6 address as a host/port pair.
- Store hosts and ports separately; never pass a combined `IP:port` value to ping.

Example:

```text
Device: Raspberry Pi
Host:   192.168.1.20

Services:
  Home Assistant    8123    HTTP
  Admin Dashboard   8443    HTTPS
  SSH                 22    No browser link
```

### Monitoring Behavior

- Preserve host ping status independently of service status. A reachable host may
  have an unavailable service.
- Check each configured port using a TCP connection with a connection timeout.
- Give each service its own status and consecutive-failure counter.
- Start services as `unknown`. A successful check marks the service `online` and
  resets its failures; three consecutive failed checks mark it `offline`.
- Record actual service status transitions without creating duplicate events when
  status is unchanged.
- Treat successful TCP connection establishment as port availability, not proof
  that an application returns healthy HTTP responses.

### Dashboard and Links

- Show named services, port numbers, and independent status badges in device details.
- Provide an **Open** link for HTTP and HTTPS services, built from the selected
  scheme, device host, and port; for example, `http://192.168.1.20:8123/`.
- Format IPv6 URLs with brackets around the host.
- Do not create a browser link for services configured with no browser link.
- Inherit guest visibility from the parent device, including service details and
  links. Keep transition-history access restricted to admins.
- Include service transitions in Activity, distinguished from host transitions
  and labelled with device name, service name, and port. For example:
  `Raspberry Pi · Home Assistant (8123): online → offline`.

### Implementation and Verification

- Add service persistence, API schemas/endpoints, and a reviewed Alembic migration
  that preserves existing devices and ping history. Devices do not need services
  after the upgrade.
- Delete service records and their history when their parent device is deleted.
- Extend the monitor worker, device-management forms, details, and Activity page.
- Verify IP-only devices, multiple named ports, validation, duplicate-port handling,
  TCP success/failure and recovery, independent host/service status, link generation,
  guest/admin access, and migration upgrade/downgrade behavior.

### Current Implementation

This feature is not implemented yet. The current monitor checks hosts using ping;
configure the host without a port until named-port support is implemented.
