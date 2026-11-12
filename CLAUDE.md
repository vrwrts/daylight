# Daylight

A Home Assistant custom integration, installed through HACS, that sets the brightness and colour temperature of lights along a daily curve between wake and sleep times. There is one config entry with the shared schedule and curve. Each profile is a subentry: a set of lights with its own values along that curve.

- `light.turn_on` and `light.turn_off` are intercepted (`interceptor.py`, `hub.py`). Turn-ons get the current values filled in. A turn-off holds back Daylight's own commands so they can't undo it.
- Lights that are on are updated on one shared interval and when schedule or night mode entities change (`__init__.py`). Each profile computes its own target (`profile.py`).
- A light changed by hand goes under manual control until it is turned off or a timeout runs out. `daylight.pause` puts lights under manual control until `daylight.resume`, stored across restarts. `daylight.resume` ends manual control.
- Night mode swaps the curve for fixed values while an entity, such as an `input_boolean`, is on.
- The integration provides triggers and conditions for manual control (`trigger.py`, `condition.py`).

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/) for every commit message and PR title. The release process depends on it. Examples: `fix: let light.turn_off win over Daylight's own updates`, `feat: …`, `docs: …`, `test: …`, `chore: …`. Mark breaking changes with `!` (`feat!: …`) or a `BREAKING CHANGE:` footer.

In the commit body, say why the change was made. PR descriptions use the sections Why, What changed, Not covered (if anything was left out on purpose) and Testing. On GitHub, don't hard-wrap Markdown paragraphs.

## Code

- Comments say why, not what. Keep them sparse, like the surrounding code. Public methods get a one-line docstring that doesn't just repeat the signature.
- Constants go in `const.py`. Tuning values like `QUIET_WINDOW_MARGIN` and `OFF_WAIT_TIMEOUT` get a comment explaining why they exist.
- Only `interceptor.py` touches Home Assistant's private service registry. If the internals change, setup must fail loudly with `InterceptorError`/`ConfigEntryError` rather than run without interception.
- Daylight's own service calls use `hub.new_context()`, so the hub can tell them apart from user and automation calls.
- Spell user-facing text in British English ("colour", "initialise"), as the existing code and README do.

## Docs

- `README.md` is the user documentation. Update it in the same change as any user-visible behaviour change.
- Write plainly. No em dashes: use commas or split the sentence.

## Tests

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
```

- Tests use `pytest-homeassistant` with `MockLight` and the helpers in `tests/conftest.py` (`add_profile`, `turn_on`, `turn_off`), plus `freezer` for time.
- A test for a bug fix should fail without the fix. Check this before opening the PR.
- CI runs pytest, hassfest and the HACS action (`.github/workflows`).
