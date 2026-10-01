import esphome.automation as automation
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import pins
from esphome.components import remote_base, remote_receiver, sensor, spi, text_sensor
from esphome.const import CONF_ID

# Composant d'extraction de trames Vevor 7-en-1 depuis le flux démodulé du CC1101.
#
# Rôle volontairement limité : convertir des impulsions en octets et remettre la trame brute au
# YAML (trigger `on_frame`). La logique de protocole (en-tête, checksum, compteur, plages de
# valeurs) vit dans `includes/vevor_7in1.h`, du C++ pur testable sans matériel
# (`tools/run_tests.sh`). Cette séparation permet de tester le décodage à froid et de ne
# reflasher que pour la partie radio.
#
# Second rôle (instrumentation) : le composant est aussi un périphérique du MÊME bus SPI que le
# CC1101 (même `cs_pin`), uniquement pour LIRE des registres de diagnostic (RSSI, MARCSTATE,
# PKTSTATUS, FREQ2/1/0) et les publier dans les entités `rssi_sensor` / `radio_sensor`. En mode
# série asynchrone, le composant `cc1101` d'ESPHome ne publie aucun RSSI : sans cette lecture,
# « aucune trame » ne distingue pas « pas d'énergie RF » de « énergie reçue mais démodulation
# muette ». Aucune écriture n'est faite dans la puce.

CODEOWNERS = ["@projet-vevor-7in1"]
DEPENDENCIES = ["remote_receiver", "spi"]

CONF_RECEIVER_ID = "receiver_id"
CONF_BIT_PERIOD = "bit_period"
CONF_PROBE_PIN = "probe_pin"
CONF_ON_FRAME = "on_frame"
CONF_RSSI_SENSOR = "rssi_sensor"
CONF_RADIO_SENSOR = "radio_sensor"
CONF_INVENTORY_SENSOR = "inventory_sensor"

vevor_7in1_ns = cg.esphome_ns.namespace("vevor_7in1")
Vevor7in1 = vevor_7in1_ns.class_(
    "Vevor7in1",
    cg.Component,
    remote_base.RemoteReceiverDumperBase,
    spi.SPIDevice,
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Vevor7in1),
            cv.Required(CONF_RECEIVER_ID): cv.use_id(
                remote_receiver.RemoteReceiverComponent
            ),
            # Période bit nominale : 90 µs (valeur du protocole publiée et du montage témoin qui
            # décode) — le composant essaie de toute façon plusieurs périodes voisines à chaque
            # capture, ce paramètre n'est qu'un point de départ pour les logs.
            cv.Optional(CONF_BIT_PERIOD, default="90us"): cv.positive_time_period_microseconds,
            cv.Optional(CONF_PROBE_PIN): pins.internal_gpio_input_pin_schema,
            # Entités de diagnostic alimentées par les lectures SPI (facultatives).
            cv.Optional(CONF_RSSI_SENSOR): cv.use_id(sensor.Sensor),
            cv.Optional(CONF_RADIO_SENSOR): cv.use_id(text_sensor.TextSensor),
            cv.Optional(CONF_INVENTORY_SENSOR): cv.use_id(text_sensor.TextSensor),
            cv.Optional(CONF_ON_FRAME): automation.validate_automation(single=True),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    # Second périphérique du bus SPI du CC1101 : même horloge/ordre/mode que lui (1 MHz, mode 0).
    .extend(spi.spi_device_schema(cs_pin_required=False))  # cs_pin reste DECLARE dans le YAML du
    # projet ; il devient seulement facultatif, ce qui permet la variante de test V2 (aucun second
    # peripherique SPI sur le bus, comme le montage temoin) sans toucher au reste du composant.
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    receiver = await cg.get_variable(config[CONF_RECEIVER_ID])
    cg.add(var.set_receiver(receiver))
    cg.add(var.set_bit_period(int(config[CONF_BIT_PERIOD].total_microseconds)))
    if CONF_PROBE_PIN in config:
        probe_pin = await cg.gpio_pin_expression(config[CONF_PROBE_PIN])
        cg.add(var.set_probe_pin(probe_pin))

    # Enregistrement sur le bus SPI (le bus est mis en place par le composant `spi`, dont la
    # priorité de setup est plus haute : nos lectures ne peuvent pas partir avant lui).
    await spi.register_spi_device(var, config)

    if CONF_RSSI_SENSOR in config:
        cg.add(var.set_rssi_sensor(await cg.get_variable(config[CONF_RSSI_SENSOR])))
    if CONF_RADIO_SENSOR in config:
        cg.add(var.set_radio_sensor(await cg.get_variable(config[CONF_RADIO_SENSOR])))
    if CONF_INVENTORY_SENSOR in config:
        cg.add(var.set_inventory_sensor(await cg.get_variable(config[CONF_INVENTORY_SENSOR])))

    if CONF_ON_FRAME in config:
        await automation.build_automation(
            var.get_frame_trigger(),
            [(cg.std_vector.template(cg.uint8), "x")],
            config[CONF_ON_FRAME],
        )
