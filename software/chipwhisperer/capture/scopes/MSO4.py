import pyvisa

from chipwhisperer.logging import *
from ...common.utils import util

class MSO4TriggerSettings(util.DisableNewAttr):
    """Trigger config for the MSO 4-Series

    Attributes:
        typ: The type of event to use as a trigger.
        source: The source of the event currently configured as a trigger.
        coupling: The coupling of the trigger source.
        level: The trigger level.
        event: The event channel (A or B) to use as a trigger.
            See: 4/5/6 Series MSO Help (https://www.tek.com/en/sitewide-content/manuals/4/5/6/4-5-6-series-mso-help)
            § Trigger on sequential events (A and B triggers)
    """

    modes = ['edge', 'width', 'timeout', 'runt', 'window', 'logic', 'sethold', 'transition', 'bus']
    implemented_modes = ['edge'] # I know, sorry...
    sources = ['ch1', 'ch2', 'ch3', 'ch4', 'auxiliary', 'aux', 'line'] # NOTE: Digital channels are not supported
    couplings = ['dc', 'hfrej', 'lfrej', 'noiserej']
    events = ['A', 'B']

    def __init__(self, res: pyvisa.resources.MessageBasedResource, event: str = 'A'):
        super().__init__()

        self.sc: pyvisa.resources.MessageBasedResource = res
        if event not in MSO4TriggerSettings.events:
            raise ValueError(f'Invalid event {event}. Valid events: {MSO4TriggerSettings.events}')
        self.event = event
        self._clear_caches()
        self.disable_newattr()

    def _clear_caches(self):
        self._cached_typ = None
        self._cached_source = None
        self._cached_coupling = None
        self._cached_level = None
        self._cached_edge_slope = None

    def _get_type(self) -> str:
        if not self._cached_typ:
            self._cached_typ = self.sc.query(f'TRIGGER:{self.event}:TYPE?').strip()
        return self._cached_typ

    def _set_typ(self, typ: str) -> None:
        if self._cached_typ == typ:
            return
        self._cached_typ = typ
        self.sc.write(f'TRIGGER:{self.event}:TYPE {typ}')

    @property
    def typ(self):
        """The type of event to use as a trigger.
        Raises:
           ValueError: if value is not one of the allowed strings
           NotImplementedError: if value is not implemented (e.g. Bus values,
        """
        return self._get_type()
    @typ.setter
    def typ(self, mode: str):
        if mode.lower() not in MSO4TriggerSettings.modes:
            raise ValueError(f'Invalid trigger mode {mode}. Valid modes: {MSO4TriggerSettings.modes}')
        if mode.lower() not in MSO4TriggerSettings.implemented_modes:
            raise NotImplementedError(f'Trigger mode {mode} is not implemented. Supported modes: {MSO4TriggerSettings.implemented_modes}')
        self._set_typ(mode)

    def _get_source(self, trig_typ: str = "") -> str:
        if not trig_typ:
            trig_typ = self._get_type()
        if not self._cached_source:
            self._cached_source = self.sc.query(f'TRIGGER:{self.event}:{trig_typ}:SOURCE?').strip()
        return self._cached_source

    def _set_source(self, trig_typ: str, src: str) -> None:
        if self._cached_source == src:
            return
        self._cached_source = src
        self.sc.write(f'TRIGGER:{self.event}:{trig_typ}:SOURCE {src}')

    @property
    def source(self):
        """The source of the event currently configured as a trigger.
        Raises:
            ValueError: if value is not one of the allowed strings
        """
        return self._get_source(self.typ)
    @source.setter
    def source(self, src: str):
        if src.lower() not in MSO4TriggerSettings.sources:
            raise ValueError(f'Invalid trigger source {src}. Valid sources: {MSO4TriggerSettings.sources}')
        self._set_source(self.typ, src)

    def _get_coupling(self, trig_typ: str) -> str:
        if not self._cached_coupling:
            self._cached_coupling = self.sc.query(f'TRIGGER:{self.event}:{trig_typ}:COUPLING?').strip()
        return self._cached_coupling

    def _set_coupling(self, trig_typ: str, coupling: str) -> None:
        if self._cached_coupling == coupling:
            return
        self._cached_coupling = coupling
        self.sc.write(f'TRIGGER:{self.event}:{trig_typ}:COUPLING {coupling}')

    @property
    def coupling(self):
        """The coupling of the trigger source.
        Raises:
            ValueError: if value is not one of the allowed strings
        """
        return self._get_coupling(self.typ)
    @coupling.setter
    def coupling(self, coupling: str):
        if coupling.lower() not in MSO4TriggerSettings.couplings:
            raise ValueError(f'Invalid trigger coupling {coupling}. Valid coupling: {MSO4TriggerSettings.couplings}')
        self._set_coupling(self.typ, coupling)

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
        # self._cached_level = level
        self.sc.write(f'TRIGGER:{self.event}:LEVEL:{self._get_source()} {level:.4e}')
        # TODO check EXE register to verify the level was set correctly

    @property
    def level(self):
        """The trigger level.
        Raises:
            ValueError: if value is not a float
        """
        return self._get_level()
    @level.setter
    def level(self, level: float):
        if not isinstance(level, float) and not isinstance(level, int):
            raise ValueError(f'Invalid trigger level {level}. Must be a float or an int.')
        self._set_level(level)

class MSO4:
    """Tektronix MSO 4-Series scope object.
    """

    _name = "ChipWhisperer/MSO4"

    def __init__(self):
        self.rm: pyvisa.ResourceManager = None # type: ignore
        self.sc: pyvisa.resources.MessageBasedResource = None # type: ignore
        self.trig: MSO4TriggerSettings = None # type: ignore

        self.connectStatus = False

    def _id_scope(self) -> dict:
        """Read identification string from scope

        Raises:
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        """

        try:
            idn = self.sc.query('*IDN?') # TEKTRONIX,MSO44,C019654,CF:91.1CT FV:2.0.3.950
        except Exception:
            self.dis()
            raise

        s = idn.split(',')
        if len(s) != 4:
            raise IOError("Invalid IDN string returned from scope")
        return {
            'vendor': s[0],
            'model': s[1],
            'serial': s[2],
            'firmware': s[3]
        }

    def con(self, ip: str = "", **kwargs) -> bool:
        """Connect to scope.

        Args:
            ip: IP address of scope
            kwargs: Additional arguments to pass to pyvisa.ResourceManager.open_resource

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: IP address must be specified
            OSError: Invalid vendor or model returned from scope
        """
        if ip == "":
            raise ValueError("IP address must be specified")

        self.rm = pyvisa.ResourceManager()
        self.sc = self.rm.open_resource(f'TCPIP::{ip}::INSTR') # type: ignore
        self.trig = MSO4TriggerSettings(self.sc)

        sc_id = self._id_scope()
        if sc_id['vendor'] != 'TEKTRONIX':
            raise OSError(f'Invalid vendor returned from scope {sc_id["vendor"]}')
        if sc_id['model'] not in ['MSO44', 'MSO46']:
            raise OSError(f'Invalid model returned from scope {sc_id["model"]}')

        self.connectStatus = True
        return True

    def dis(self) -> bool:
        """Disconnect from scope.
        """
        self.sc.close()
        self.rm.close()

        self.trig = None # type: ignore

        self.connectStatus = False
        return True

    def arm(self) -> None:
        """Setup scope to begin capture/glitching when triggered.

        The scope must be armed before capture or glitching (when set to
        'ext_single') can begin.

        Raises:
            OSError: Scope isn't connected.
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        """

        if self.connectStatus is False:
            raise OSError("Scope is not connected. Connect it first...")
        
        try:
            pass
        except Exception:
            self.dis()
            raise

        pass

    def capture(self):
        """Reads power trace data from the scope.
        
        Returns:
            False upon success and True upon failure
        """
        pass

    def get_last_trace(self):
        """Returns the scope data read by capture()

        Returns:
            A numpy array containing the scope data.
        """
        pass
