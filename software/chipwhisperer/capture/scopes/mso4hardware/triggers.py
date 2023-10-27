from typing import Type, Union

import pyvisa

from chipwhisperer.common.utils import util
from chipwhisperer.logging import scope_logger

class MSO4TriggerBase(util.DisableNewAttr):
    '''Base trigger for the MSO 4-Series, used for settings shared by
    all trigger types

    Attributes:
        source: The source of the event currently configured as a trigger.
        coupling: The coupling of the trigger source.
        level: The trigger level.
        event: The event channel (A or B) to use as a trigger.
            See: 4/5/6 Series MSO Help § Trigger on sequential events (A and B triggers)
            (https://www.tek.com/en/sitewide-content/manuals/4/5/6/4-5-6-series-mso-help)
            NOTE: Writing this attribute won't directly change the trigger mode on
                  the scope. Most likely, you just want to use MSO4SequenceTrigger
                  instead of touching this.
        mode: The trigger mode (auto/normal)
    '''

    _name = "ChipWhisperer/MSO4BaseTrigger"

    sources = ['ch1', 'ch2', 'ch3', 'ch4', 'auxiliary', 'aux', 'line'] # NOTE: Digital channels are not supported yet
    couplings = ['dc', 'hfrej', 'lfrej', 'noiserej']
    events = ['A', 'B']
    modes = ['auto', 'normal']

    _type = None

    def __init__(self, res: pyvisa.resources.MessageBasedResource, event: str = 'A'):
        super().__init__()

        self.sc: pyvisa.resources.MessageBasedResource = res
        if event not in MSO4TriggerBase.events:
            raise ValueError(f'Invalid event {event}. Valid events: {MSO4TriggerBase.events}')
        self.event = event

        if not self._type:
            raise NotImplementedError("Can't instantiate MSO4TriggerBase directly. Use a subclass instead.")
        self._set_type(self._type)

        self._cached_source = None
        self._cached_coupling = None
        self._cached_level = None
        self._cached_mode = None

    def clear_caches(self):
        '''Resets the local configuration cache so that values will be fetched from
        the scope.

        This is useful when the scope configuration is (potentially) changed externally.
        '''
        self._cached_source = None
        self._cached_coupling = None
        self._cached_level = None
        self._cached_mode = None

    def _set_type(self, typ: str) -> None:
        self.sc.write(f'TRIGGER:{self.event}:TYPE {typ}')

    def _get_source(self) -> str:
        if not self._cached_source:
            self._cached_source = self.sc.query(f'TRIGGER:{self.event}:{self._type}:SOURCE?').strip()
        return self._cached_source

    def _set_source(self, src: str) -> None:
        if self._cached_source == src:
            return
        self._cached_source = src
        self.sc.write(f'TRIGGER:{self.event}:{self._type}:SOURCE {src}')

    @property
    def source(self):
        '''The source of the event currently configured as a trigger.
        Cached

        Raises:
            ValueError: if value is not one of the allowed strings
        '''
        return self._get_source()
    @source.setter
    def source(self, src: str):
        if src.lower() not in MSO4TriggerBase.sources:
            raise ValueError(f'Invalid trigger source {src}. Valid sources: {MSO4TriggerBase.sources}')
        self._set_source(src)

    def _get_coupling(self) -> str:
        if not self._cached_coupling:
            self._cached_coupling = self.sc.query(f'TRIGGER:{self.event}:{self._type}:COUPLING?').strip()
        return self._cached_coupling
    def _set_coupling(self, coupling: str) -> None:
        if self._cached_coupling == coupling:
            return
        self._cached_coupling = coupling
        self.sc.write(f'TRIGGER:{self.event}:{self._type}:COUPLING {coupling}')

    @property
    def coupling(self):
        '''The coupling of the trigger source.
        Cached

        Raises:
            ValueError: if value is not one of the allowed strings
        '''
        return self._get_coupling()
    @coupling.setter
    def coupling(self, coupling: str):
        if coupling.lower() not in MSO4TriggerBase.couplings:
            raise ValueError(f'Invalid trigger coupling {coupling}. Valid coupling: {MSO4TriggerBase.couplings}')
        self._set_coupling(coupling)

    def _get_level(self) -> float:
        if not self._cached_level:
            resp = self.sc.query(f'TRIGGER:{self.event}:LEVEL:{self._get_source()}?').strip()
            try:
                self._cached_level = float(resp)
            except ValueError as exc:
                raise ValueError(f'Got invalid trigger level from oscilloscope `{resp}`. Must be a float.') from exc
        return self._cached_level
    def _set_level(self, level: float) -> None:
        if self._cached_level == level:
            return
        self.sc.write(f'TRIGGER:{self.event}:LEVEL:{self._get_source()} {level:.4e}')

        # Check actual level
        # TODO check EXE bit in Standard Event Status Register (SESR) ('*ESR?')
        # to verify the level was set correctly.
        # This is currently not possible as the SESR is not updated in this scenario
        # on firmware 2.0.3.950

        # Workaround
        self._cached_level = None
        self._cached_level = self._get_level()
        if self._cached_level != level:
            scope_logger.warning('Failed to set trigger level to %f. Got %f instead.', level, self._cached_level)

    @property
    def level(self):
        '''The trigger level.
        Cached

        Raises:
            ValueError: if value is not a float
        '''
        return self._get_level()
    @level.setter
    def level(self, level: float):
        if not isinstance(level, float) and not isinstance(level, int):
            raise ValueError(f'Invalid trigger level {level}. Must be a float or an int.')
        self._set_level(level)

    def _get_mode(self) -> str:
        if not self._cached_mode:
            self._cached_mode = self.sc.query('TRIGGER:A:MODe?').strip()
        return self._cached_mode
    def _set_mode(self, mode: str) -> None:
        if self._cached_mode == mode:
            return
        self._cached_mode = mode
        self.sc.write(f'TRIGGER:A:MODe {mode}')

    @property
    def mode(self):
        '''The trigger mode (auto/normal).
        Cached

        Raises:
            NotImplementedError: if trigger event is not A
            ValueError: if value is not one of the allowed strings
        '''
        if self.event != 'A':
            raise NotImplementedError('Trigger mode is only supported for event A.')
        return self._get_mode()
    @mode.setter
    def mode(self, mode: str):
        if self.event != 'A':
            raise NotImplementedError('Trigger mode is only supported for event A.')
        if mode.lower() not in MSO4TriggerBase.modes:
            raise ValueError(f'Invalid trigger mode {mode}. Valid modes: {MSO4TriggerBase.modes}')
        self._set_mode(mode)

class MSO4EdgeTrigger(MSO4TriggerBase):
    '''Edge trigger

    Attributes:
        source: The source of the event currently configured as a trigger.
        coupling: The coupling of the trigger source.
        level: The trigger level.
        event: The event channel (A or B) to use as a trigger.
            See: 4/5/6 Series MSO Help (https://www.tek.com/en/sitewide-content/manuals/4/5/6/4-5-6-series-mso-help)
            § Trigger on sequential events (A and B triggers)
            NOTE: Most likely, you just want to use MSO4SequenceTrigger instead of this.
        mode: The trigger mode (auto/normal)
        edge_slope: The edge slope (rise/fall/either)
    '''

    _name = "ChipWhisperer/MSO4EdgeTrigger"
    _type = 'EDGE'

    slopes = ['rise', 'fall', 'either']

    def __init__(self, res: pyvisa.resources.MessageBasedResource, event: str = 'A'):
        super().__init__(res, event)

        self._cached_edge_slope = None
        self.disable_newattr()

    def clear_caches(self):
        super().clear_caches()
        self._cached_edge_slope = None

    def _get_edge_slope(self) -> str:
        if not self._cached_edge_slope:
            self._cached_edge_slope = self.sc.query(f'TRIGGER:{self.event}:EDGE:SLOpe?').strip()
        return self._cached_edge_slope
    def _set_edge_slope(self, slope: str) -> None:
        if self._cached_edge_slope == slope:
            return
        self._cached_edge_slope = slope
        self.sc.write(f'TRIGGER:{self.event}:EDGE:SLOpe {slope}')

    @property
    def edge_slope(self):
        '''The edge slope (rise/fall/either).
        Cached

        Raises:
            ValueError: if value is not one of the allowed strings
        '''
        return self._get_edge_slope()
    @edge_slope.setter
    def edge_slope(self, slope: str):
        if slope.lower() not in MSO4EdgeTrigger.slopes:
            raise ValueError(f'Invalid edge slope {slope}. Valid slopes: {MSO4EdgeTrigger.slopes}')
        self._set_edge_slope(slope)

class MSO4WidthTrigger(MSO4TriggerBase):
    '''Pulse Width trigger

    Attributes:
        typ: The type of event to use as a trigger.
        source: The source of the event currently configured as a trigger.
        coupling: The coupling of the trigger source.
        level: The trigger level.
        event: The event channel (A or B) to use as a trigger.
            See: 4/5/6 Series MSO Help (https://www.tek.com/en/sitewide-content/manuals/4/5/6/4-5-6-series-mso-help)
            § Trigger on sequential events (A and B triggers)
        mode: The trigger mode (auto/normal)
        lowlimit (float): The low limit of the pulse width.
        highlimit (float): The high limit of the pulse width.
        when (str): When to trigger (lessthan/morethan/equal/unequal/within/outside)
        polarity (str): The polarity of the pulse (positive/negative)
    '''

    _name = "ChipWhisperer/MSO4WidthTrigger"
    _type = 'WIDth'

    whens = ['lessthan', 'morethan', 'equal', 'unequal', 'within', 'outside']

    def __init__(self, res: pyvisa.resources.MessageBasedResource, event: str = 'A'):
        super().__init__(res, event)

        self._cached_when = None
        self._cached_limit = None
        self.disable_newattr()

    def clear_caches(self):
        super().clear_caches()
        self._cached_when = None
        self._cached_limit = None

    # TODO lowlimit, highlimit, when & polarity properties

MSO4Triggers = Type[MSO4EdgeTrigger] | Type[MSO4WidthTrigger]
