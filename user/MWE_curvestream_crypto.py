import pyvisa as visa
import chipwhisperer as cw
import time

print("set up VISA connection")

rm = visa.ResourceManager()

scope_address = "TCPIP0::192.168.1.140::inst0::INSTR"

scope: visa.resources.MessageBasedResource = rm.open_resource(scope_address) # type: ignore
scope.timeout = 20000

print("reset scope")
scope.write("*RST")
scope.write("*CLS")

#turn off all the waveform displays
print("turn off waveform display")
scope.write("display:waveform 0")

print("set up scope")

scope.write("CH1:SCAle 1")

scope.write("HORizontal:MODe manual")
scope.write("HORizontal:MODe:SAMPlerate 6.25e9")
scope.write('HORizontal:SCAle 200e-9')
scope.write('HORizontal:POSition 10')

scope.write("TRIGger:A:TYPe EDGE")
scope.write("TRIGger:A:EDGE:SOURce CH1")
scope.write("TRIGger:A:LEVEL:CH1 1.4")
scope.write("TRIGger:A:EDGE:SLOPe RISE")
scope.write("TRIGger:A:MODe NORMAL")

scope.write("ACQuire:FASTAcq:STATE ON")

# Configure the target
# On the CW305, setting force=False only programs the FPGA if it is currently unprogrammed, whereas force=True programs the FPGA regardless.
# This option isn't available on the CW312T_A35 or CW312T_ICE40.
fpga_id = '100t'
target = cw.target(None, cw.targets.CW305, force=True, fpga_id=fpga_id)

# run at 10 MHz:
target.pll.pll_outfreq_set(10E6, 1)

# Acquire 1000 traces
traces = []
# scope.write("display:waveform 1")
# Enable curvestream mode
scope.write("CURVEStream?") # Must be done here???
for i in range(1000):
    print(i, end="\r", flush=True)
    target.simpleserial_write('p', b'\x00' * 16)
    response = target.simpleserial_read('r', target.output_len, ack=True)
    trace = scope.read_raw()
    traces.append(trace)

print(len(traces))
scope.write("*CLS")
