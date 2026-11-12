# Daylight

A Home Assistant integration that adjusts the brightness and colour temperature of your lights through the day.

Lights follow a clock-based curve: they come on warm and dim after waking, ramp up to a daytime peak, and wind down again before bedtime. When an automation calls `light.turn_on` or `light.toggle` on a managed light, Daylight fills in the current brightness and colour temperature, so lights come on at the right values straight away instead of being corrected afterwards. If you change a light yourself, Daylight stops adapting it until you turn it off or a timeout runs out.

The curve is ported from [JEHA](https://github.com/vpetersson/jeha). Intercepting `light.turn_on` works the way [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting) does it.

Daylight creates no entities.

## Installation

Requires Home Assistant 2026.11 or later.

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Add `https://github.com/vrwrts/daylight` with type **Integration**.
3. Install **Daylight** and restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration** and choose **Daylight**.

## Setup

Daylight has one entry. It holds the settings all your lights share: the schedule, the curve, manual control, whether winter brightening is on, and the night mode entity. Change them with **Configure** on the Daylight entry.

Lights are added through profiles. A profile is a set of lights with its own brightness and colour temperature at wake, peak and sleep, and its own night and winter values. Every profile follows the same schedule and curve. Add as many as you like with **Add profile**, for example a normal one and a dimmed one for a hallway. Change a profile with its **Reconfigure** option.

Changing the Daylight settings or any profile restarts all profiles, which ends manual control on every light. Paused lights stay paused.

To stop Daylight from adapting some lights, [pause](#daylightpause) them or delete their profile. To turn Daylight off completely, disable its entry.

### Upgrading from 0.2 or earlier

Earlier versions made each profile its own Daylight entry with its own schedule and curve. On the first start after upgrading, Daylight merges them into one entry:

- every old entry becomes a profile, including disabled ones;
- the shared settings come from the oldest enabled entry, and that entry is the one kept;
- if other entries had different shared settings, those are dropped. Daylight logs a warning and shows a repair issue listing them.

This can't be undone. Take a backup first if you want a way back.

## Daylight settings

These apply to every profile.

### Schedule

| Option | Default | |
|---|---|---|
| Wake time | 07:00 | Start of the morning ramp. |
| Wake time entity | none | Optional. Replaces the wake time while it has a valid value. |
| Sleep time | 23:00 | End of the evening ramp. |
| Sleep time entity | none | Optional. Replaces the sleep time while it has a valid value. |

The entities can be timestamp sensors (such as `sensor.next_alarm`), `input_datetime` helpers or time entities. Daylight uses the local time of day and ignores the date, so an alarm set for tomorrow at 06:45 means 06:45. If the entity is unavailable, unknown or holds no time, the fixed time is used. A change to either entity applies straight away.

A sleep time after midnight works, and so does a wake time later than the sleep time.

### Curve

| Option | Default | |
|---|---|---|
| Ramp duration | 120 min | Length of the morning and evening ramps. |
| Curve | Cosine | Cosine or linear. |
| Transition | 10 s | Fade used for periodic updates. |
| Update interval | 60 s | How often lights that are on get the current values. |

Over a day:

- **From wake time:** the morning ramp runs from the wake values to the peak values.
- **Daytime:** lights hold the peak values.
- **Before sleep time:** the evening ramp runs from the peak values to the sleep values and ends at sleep time.
- **Overnight:** lights hold the sleep values.

If the time between wake and sleep is shorter than two ramps, both ramps are shortened to meet in the middle.

With the cosine curve, the morning ramp starts and ends gently. The evening ramp changes fastest at the start and settles toward the sleep values.

### Winter brightening

| Option | Default |
|---|---|
| Enabled | off |

When enabled, each profile's wake and peak brightness move toward its winter values as days get shorter. Day length comes from your home's latitude. At 18 hours of daylight or more, the normal values apply. At 6 hours or fewer, the winter values apply. Between those, the values are blended. Sleep brightness and colour temperature don't change.

### Manual control

| Option | Default | |
|---|---|---|
| Mode | Pause until turned off | Or **pause for a set time**. |
| Timeout | 30 min | Used when pausing for a set time. |
| Brightness tolerance | 6 % | Smaller changes don't count as manual. |
| Colour temperature tolerance | 150 K | Smaller changes don't count as manual. |

A light goes under manual control when:

- a `light.turn_on` call sets its brightness or colour, for example a movie scene setting it to 30 %. Daylight fills in whatever that call left out, then stops adapting the light;
- its brightness, colour temperature or colour mode changes by more than the tolerance, and the change didn't come from Daylight. This includes changes made outside Home Assistant, such as with a Zigbee remote. Changes reported within the transition time plus 5 seconds of Daylight's own last command are ignored, because lights report in-between values while they fade.

Manual control ends when:

- the light turns off;
- the timeout runs out, in "pause for a set time" mode. Another manual change restarts the timer. When it ends, the light is adapted straight away;
- you call `daylight.resume`.

A paused light stays under manual control until `daylight.resume`, see [`daylight.pause`](#daylightpause).

A `light.toggle` call is treated as `light.turn_on` for lights it turns on and as `light.turn_off` for lights it turns off. A light that's turned on outside Home Assistant (wall switch, remote) comes on at its old values. Daylight corrects it straight away.

### Night mode

| Option | Default | |
|---|---|---|
| Night mode entity | none | Optional. For example an `input_boolean`. |

While the entity is on, each profile uses its night values instead of the curve. When the entity changes, lights that are on and not under manual control get the new values straight away. Manual control works the same as during the day.

If an automation turns lights off on the same change, as many bedtime automations do, the turn-off wins. Daylight lets its own command reach the light first and sends nothing more to that light until the turn-off has landed. This covers `light.turn_off` and `light.toggle` calls made through Home Assistant, not switches that talk to the lights directly.

## Profile settings

### Name and lights

Any mix of lights, devices, areas, floors and labels. The target is stored as you chose it and resolved again whenever the entity, device or area registry changes. So if your profile targets a "Circadian" label, putting that label on a new light adds it to the profile.

Home Assistant light groups are replaced by their members, and each member is adapted on its own. Groups from other integrations, such as Zigbee2MQTT or Hue groups, are treated as single lights.

If a light ends up in more than one profile, the oldest profile adapts it and the others leave it alone. Daylight logs a warning and shows a repair issue on the other profiles until the overlap is gone.

### Brightness and colour temperature

| Option | Brightness | Colour temperature |
|---|---|---|
| At wake | 65 % | 2000 K |
| Peak | 100 % | 3000 K |
| At sleep | 30 % | 2000 K |

### Winter values

| Option | Default |
|---|---|
| Winter brightness at wake | 90 % |
| Winter peak brightness | 100 % |

Only used when winter brightening is enabled in the Daylight settings.

### Night values

| Option | Default |
|---|---|
| Night brightness | 1 % |
| Night colour temperature | 2000 K |

Used while the night mode entity in the Daylight settings is on.

## Light capabilities

Daylight sends brightness and colour temperature to lights that support colour temperature, clamped to each light's range. Lights that only dim get brightness only. On/off lights are left alone. Calls that use `flash` or `effect` are passed through unchanged.

## Actions

### `daylight.pause`

Stops adapting the lights until you call `daylight.resume`. A paused light stays paused when it's turned off, when a manual control timeout runs out, and across restarts and changes to the settings. While paused, a light is under manual control: Daylight fills in nothing when it turns on and doesn't correct it. A target is required, as for `daylight.resume`. Lights that no profile adapts are ignored.

```yaml
action: daylight.pause
target:
  entity_id: light.desk
```

### `daylight.resume`

Ends manual control, including a pause, and adapts the lights straight away. A target is required: lights, devices, areas, floors or labels. Light groups are expanded to their members. Each light is resumed by the profile that adapts it, so one call can cover lights from several profiles. Lights that no profile adapts are ignored.

```yaml
action: daylight.resume
target:
  area_id: living_room
```

## Triggers

Both take a light target. They fire for lights in the target that belong to a Daylight profile.

- **Manual control started** (`daylight.manual_control_started`): `trigger.reason` is `explicit_values`, `external_change` or `paused`. Pausing a light that's already under manual control doesn't fire it again.
- **Manual control ended** (`daylight.manual_control_ended`): `trigger.reason` is `turned_off`, `timeout` or `resume`.

Both also set `trigger.entity_id`, `trigger.profile` (the profile's name) and `trigger.subentry_id` (the profile's id).

```yaml
triggers:
  - trigger: daylight.manual_control_started
    target:
      area_id: living_room
actions:
  - action: notify.mobile_app_phone
    data:
      message: "Daylight paused {{ trigger.entity_id }} ({{ trigger.reason }})"
```

## Conditions

Both take a light target and pass if **any** or **all** of its lights match.

- **Light is adapted by Daylight** (`daylight.is_adapting`): the light is in a profile and not under manual control. A light that's off counts, because Daylight will set it when it comes on.
- **Light is under manual control** (`daylight.is_manually_controlled`): the light is in a profile and under manual control, including when it's paused.

Lights in no profile pass neither condition.

```yaml
conditions:
  - condition: daylight.is_adapting
    target:
      entity_id: light.desk
    options:
      behavior: all
```

## Private Home Assistant API

To fill in values before a light turns on, and to keep its own commands from undoing a turn-off, Daylight wraps the registered `light.turn_on`, `light.turn_off` and `light.toggle` handlers through `hass.services._services`, a private part of Home Assistant. Adaptive Lighting does the same. If a Home Assistant update changes those internals, the Daylight entry fails to set up with an error that says so, rather than running without interception. Unloading the entry restores the original handlers.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
```
