import esphome.automation as automation
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import cc1101, remote_base, remote_receiver
from esphome.const import CONF_ID

# Vevor 7-in-1 frame extractor from the CC1101 demodulated stream.
#
# Role deliberately limited: turn pulses into bytes and hand the raw frame back to the YAML
# (`on_frame` trigger). Protocol logic (header, checksum, counter, value ranges) lives in
# `includes/vevor_protocol.h`, pure C++ testable without hardware (`tools/run_tests.sh`).
#
# NO BIT-PERIOD SETTING, on purpose. The bit period is MEASURED on every burst
# (estimer_periode_x10) and several nearby values are tried on each capture: the station's crystal
# and the demodulator decide it, not the configuration. A `bit_period:` knob used to be declared
# here and was read by nobody — removed rather than left as a lie that looks like a setting.
#
# NO SPI ACCESS. A second SPI device on the CC1101 bus makes the chip mute: 0 captures and 0 frames
# with it, 5 frames/60 s without it. Removed, not disabled; the chip must stay the only device on
# its bus (see dev/docs/firmware-design-notes.md §4).

CODEOWNERS = ["@projet-vevor-7in1"]
DEPENDENCIES = ["remote_receiver", "cc1101"]

CONF_RECEIVER_ID = "receiver_id"
CONF_RADIO_ID = "radio_id"
CONF_ON_FRAME = "on_frame"
# Station identity pin. 0 (default) = learn the first station seen; any other value pins that
# station and drops every other ID (a neighbour's station on the same protocol). Decimal, like the
# "Station ID" sensor publishes it: 33995 = 0x84cb.
CONF_STATION_ID = "station_id"

# Parent component id, reused by the sub-platforms (number/).
CONF_VEVOR_7IN1_ID = "vevor_7in1_id"

vevor_7in1_ns = cg.esphome_ns.namespace("vevor_7in1")
Vevor7in1 = vevor_7in1_ns.class_(
    "Vevor7in1",
    cg.Component,
    remote_base.RemoteReceiverDumperBase,
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Vevor7in1),
            cv.Required(CONF_RECEIVER_ID): cv.use_id(
                remote_receiver.RemoteReceiverComponent
            ),
            # The radio, so the watchdog can re-arm it (cc1101.reset): the policy lives in the
            # component, the YAML only points at the radio.
            cv.Optional(CONF_RADIO_ID): cv.use_id(cc1101.CC1101Component),
            cv.Optional(CONF_STATION_ID, default=0): cv.int_range(min=0, max=0xFFFF),
            cv.Optional(CONF_ON_FRAME): automation.validate_automation(single=True),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    receiver = await cg.get_variable(config[CONF_RECEIVER_ID])
    cg.add(var.set_receiver(receiver))

    if CONF_RADIO_ID in config:
        radio = await cg.get_variable(config[CONF_RADIO_ID])
        cg.add(var.set_radio(radio))

    # 0 = learn (the default): the component adopts the first station it decodes.
    cg.add(var.set_station_id(config[CONF_STATION_ID]))

    if CONF_ON_FRAME in config:
        await automation.build_automation(
            var.get_frame_trigger(),
            [(cg.std_vector.template(cg.uint8), "x")],
            config[CONF_ON_FRAME],
        )
