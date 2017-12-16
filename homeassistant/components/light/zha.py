"""
Lights on Zigbee Home Automation networks.

For more details on this platform, please refer to the documentation
at https://home-assistant.io/components/light.zha/
"""
import asyncio
import logging

from homeassistant.components import light, zha
from homeassistant.util.color import color_RGB_to_xy
from homeassistant.const import STATE_UNKNOWN

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['zha']

DEFAULT_DURATION = 0.5


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the Zigbee Home Automation lights."""
    discovery_info = zha.get_discovery_info(hass, discovery_info)
    if discovery_info is None:
        return

    endpoint = discovery_info['endpoint']
    try:
        discovery_info['color_capabilities'] \
            = yield from endpoint.light_color['color_capabilities']
    except (AttributeError, KeyError):
        pass

    async_add_devices([Light(**discovery_info)], update_before_add=True)


class Light(zha.Entity, light.Light):
    """Representation of a ZHA or ZLL light."""

    _domain = light.DOMAIN

    def __init__(self, **kwargs):
        """Initialize the ZHA light."""
        super().__init__(**kwargs)
        self._supported_features = 0
        self._color_temp = None
        self._xy_color = None
        self._brightness = None

        import bellows.zigbee.zcl.clusters as zcl_clusters
        if zcl_clusters.general.LevelControl.cluster_id in self._in_clusters:
            self._supported_features |= light.SUPPORT_BRIGHTNESS
            self._supported_features |= light.SUPPORT_TRANSITION
        if zcl_clusters.lighting.Color.cluster_id in self._in_clusters:
            color_capabilities = kwargs.get('color_capabilities', 0x10)
            if color_capabilities & 0x10:
                self._supported_features |= light.SUPPORT_COLOR_TEMP

            if color_capabilities & 0x08:
                self._supported_features |= light.SUPPORT_XY_COLOR
                self._supported_features |= light.SUPPORT_RGB_COLOR

    @property
    def is_on(self) -> bool:
        """Return true if entity is on."""
        if self._state == STATE_UNKNOWN:
            return False
        return bool(self._state)

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        duration = kwargs.get(light.ATTR_TRANSITION, DEFAULT_DURATION)
        duration = duration * 10  # tenths of s
        if light.ATTR_COLOR_TEMP in kwargs:
            temperature = kwargs[light.ATTR_COLOR_TEMP]
            yield from self._endpoint.light_color.move_to_color_temp(
                temperature, duration)

        xy_color = None
        if light.ATTR_XY_COLOR in kwargs:
            xy_color = kwargs[light.ATTR_XY_COLOR]
        elif light.ATTR_RGB_COLOR in kwargs:
            xyb = color_RGB_to_xy(
                *(int(val) for val in kwargs[light.ATTR_RGB_COLOR]))
            xy_color = (xyb[0], xyb[1])
        if xy_color is not None:
            yield from self._endpoint.light_color.move_to_color(
                int(xy_color[0] * 65535),
                int(xy_color[1] * 65535),
                duration,
            )

        if light.ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[light.ATTR_BRIGHTNESS]
            # Move to level with on/off:
            yield from self._endpoint.level.move_to_level_with_on_off(
                brightness,
                duration
            )
        else:
            yield from self._endpoint.on_off.on()

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        yield from self._endpoint.on_off.off()

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def xy_color(self):
        """Return the XY color value [float, float]."""
        return self._xy_color

    @property
    def color_temp(self):
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._supported_features

    @asyncio.coroutine
    def async_update(self):
        """Retrieve latest state."""
        _LOGGER.debug("%s async_update", self.entity_id)

        @asyncio.coroutine
        def safe_read(cluster, attributes):
            """Swallow all exceptions from network read.

            If we throw during initialization, setup fails. Rather have an
            entity that exists, but is in a maybe wrong state, than no entity.
            """
            try:
                result, _ = yield from cluster.read_attributes(
                    attributes,
                    allow_cache=False,
                )
                return result
            except Exception:  # pylint: disable=broad-except
                return {}

        result = yield from safe_read(self._endpoint.on_off, ['on_off'])
        self._state = result.get('on_off', self._state)

        if self._supported_features & light.SUPPORT_BRIGHTNESS:
            result = yield from safe_read(self._endpoint.level,
                                          ['current_level'])
            self._brightness = result.get('current_level', self._brightness)

        if self._supported_features & light.SUPPORT_COLOR_TEMP:
            result = yield from safe_read(self._endpoint.light_color,
                                          ['color_temperature'])
            self._color_temp = result.get('color_temperature',
                                          self._color_temp)

        if self._supported_features & light.SUPPORT_XY_COLOR:
            result = yield from safe_read(self._endpoint.light_color,
                                          ['current_x', 'current_y'])
            if 'current_x' in result and 'current_y' in result:
                self._xy_color = (result['current_x'], result['current_y'])

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state.

        False if entity pushes its state to HA.
        """
        return False
