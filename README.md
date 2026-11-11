# Daylight

A Home Assistant integration that adjusts the brightness and colour temperature of your lights through the day.

Lights follow a clock-based curve: they come on warm and dim after waking, ramp up to a daytime peak, and wind down again before bedtime. When an automation calls `light.turn_on` on a managed light, Daylight fills in the current brightness and colour temperature, so lights come on at the right values straight away instead of being corrected afterwards. If you change a light yourself, Daylight stops adapting it until you turn it off or a timeout runs out.

The curve is ported from [JEHA](https://github.com/vpetersson/jeha). Intercepting `light.turn_on` works the way [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting) does it.

Daylight creates no entities.

## Installation

Requires Home Assistant 2026.11 or later.

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Add `https://github.com/vrwrts/daylight` with type **Integration**.
3. Install **Daylight** and restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration** and choose **Daylight**.

## Profiles

Each Daylight entry is a profile: a set of lights that share one curve. Add as many as you like, for example a normal one and a dimmed one for a hallway. To turn a profile off, disable its entry.

Adding a profile asks for a name and the lights. Everything else is in the profile's options (**Configure**).

## Options

### Lights

Any mix of lights, devices, areas, floors and labels. The target is stored as you chose it and resolved again whenever the entity, device or area registry changes. So if your profile targets a "Circadian" label, putting that label on a new light adds it to the profile.

Home Assistant light groups are replaced by their members, and each member is adapted on its own. Groups from other integrations, such as Zigbee2MQTT or Hue groups, are treated as single lights.

If a light ends up in more than one profile, the oldest profile adapts it and the others leave it alone. Daylight logs a warning and shows a repair issue on the other profiles until the overlap is gone.

### Schedule

| Option | Default | |
|---|---|---|
| Wake time | 07:00 | Start of the morning ramp. |
| Wake time entity | none | Optional. Replaces the wake time while it has a valid value. |
| Sleep time | 23:00 | End of the evening ramp. |
| Sleep time entity | none | Optional. Replaces the sleep time while it has a valid value. |

The entities can be timestamp sensors (such as `sensor.next_alarm`), `input_datetime` helpers or time entities. Daylight uses the local time of day and ignores the date, so an alarm set for tomorrow at 06:45 means 06:45. If the entity is unavailable, unknown or holds no time, the fixed time is used. A change to either entity applies straight away.

A sleep time after midnight works, and so does a wake time later than the sleep time.

### Brightness and colour temperature

| Option | Brightness | Colour temperature |
|---|---|---|
| At wake | 65 % | 2000 K |
| Peak | 100 % | 3000 K |
| At sleep | 30 % | 2000 K |

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
| Winter brightness at wake | 90 % |
| Winter peak brightness | 100 % |

When enabled, wake and peak brightness move toward the winter values as days get shorter. Day length comes from your home's latitude. At 18 hours of daylight or more, the normal values apply. At 6 hours or fewer, the winter values apply. Between those, the values are blended. Sleep brightness and colour temperature don't change.

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

A light that's turned on outside Home Assistant (wall switch, remote) or with `light.toggle` comes on at its old values. Daylight corrects it straight away.

### Night mode

| Option | Default | |
|---|---|---|
| Night mode entity | none | Optional. For example an `input_boolean`. |
| Night brightness | 1 % | |
| Night colour temperature | 2000 K | |

While the entity is on, Daylight uses the night values instead of the curve. When the entity changes, lights that are on and not under manual control get the new values straight away. Manual control works the same as during the day.

## Light capabilities

Daylight sends brightness and colour temperature to lights that support colour temperature, clamped to each light's range. Lights that only dim get brightness only. On/off lights are left alone. Calls that use `flash` or `effect` are passed through unchanged.

## Actions

### `daylight.resume`

Ends manual control and adapts the lights straight away. A target is required: lights, devices, areas, floors or labels. Light groups are expanded to their members. Each light is resumed by the profile that adapts it, so one call can cover lights from several profiles. Lights that no profile adapts are ignored.

```yaml
action: daylight.resume
target:
  area_id: living_room
```

## Triggers

Both take a light target. They fire for lights in the target that belong to a Daylight profile.

- **Manual control started** (`daylight.manual_control_started`): `trigger.reason` is `explicit_values` or `external_change`.
- **Manual control ended** (`daylight.manual_control_ended`): `trigger.reason` is `turned_off`, `timeout` or `resume`.

Both also set `trigger.entity_id`, `trigger.profile` and `trigger.config_entry_id`.

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
- **Light is under manual control** (`daylight.is_manually_controlled`): the light is in a profile and under manual control.

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

To fill in values before a light turns on, Daylight wraps the registered `light.turn_on` handler through `hass.services._services`, a private part of Home Assistant. Adaptive Lighting does the same. If a Home Assistant update changes those internals, Daylight profiles fail to set up with an error that says so, rather than running without interception. Unloading the last profile restores the original handler.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
```
