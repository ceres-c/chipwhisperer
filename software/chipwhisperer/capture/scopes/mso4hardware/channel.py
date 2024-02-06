import pyvisa

from chipwhisperer.common.utils import util
from chipwhisperer.logging import scope_logger

class MSO4AnalogChannel(util.DisableNewAttr):
    '''Settings for each analog channel
    
    Attributes:
        enable (bool): Enable the channel
        scale (float): Vertical scale of the channel in V
        offset (float): Vertical offset of the channel in V'''

    def __init__(self, res: pyvisa.resources.MessageBasedResource, channel: int):
        super().__init__()

        self.sc = res
        self.channel = channel

        self.disable_newattr()

    def clear_caches(self):
        '''Clear channel caches'''
        # No caches to clear, implemented to have a consistent interface
        pass

    @property
    def enable(self) -> bool:
        '''Enable the channel.
        Not cached

        :Getter: Return the enable status (bool)

        :Setter: Set the enable status (bool)
        '''
        return bool(int(self.sc.query(f'SELect:CH{self.channel}?').strip()))
    @enable.setter
    def enable(self, value: bool):
        if not isinstance(value, bool):
            raise ValueError(f'Invalid enable {value}. Must be bool')
        self.sc.write(f'SELect:CH{self.channel} {int(value)}')

    @property
    def scale(self) -> float:
        '''The vertical scale of the waveform.
        Not cached

        :Getter: Return the scale in V (float)

        :Setter: Set the scale in V (float)
        '''
        return float(self.sc.query(f'CH{self.channel}:SCAle?').strip())
    @scale.setter
    def scale(self, value: float | int):
        if not isinstance(value, float) and not isinstance(value, int):
            raise ValueError(f'Invalid scale {value}. Must be float or int')
        self.sc.write(f'CH{self.channel}:SCAle {value}')
        # Check if the scale was set correctly
        actual = self.scale
        if actual != value:
            scope_logger.warning('Channel %d scale was set to %f V, but is actually %f V', self.channel, value, actual)

    @property
    def position(self) -> float:
        '''The vertical position of the waveform.
        Not cached

        :Getter: Return the position in V (float)

        :Setter: Set the position in V (float)
        '''
        return float(self.sc.query(f'CH{self.channel}:POSition?').strip())
    @position.setter
    def position(self, value: float | int):
        if not isinstance(value, float) and not isinstance(value, int):
            raise ValueError(f'Invalid position {value}. Must be float or int')
        self.sc.write(f'CH{self.channel}:POSition {value}')
        # Check if the position was set correctly
        actual = self.position
        if actual != value:
            scope_logger.warning('Channel %d position was set to %f V, but is actually %f V', self.channel, value, actual)
