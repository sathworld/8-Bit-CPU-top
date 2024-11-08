# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.types.logic import Logic
from cocotb.types.logic_array import LogicArray

from random import randint, shuffle

CLOCK_PERIOD = 10  # 100 MHz
CLOCK_UNITS = "ns"

GLTEST = False
LocalTest = False

signal_dict = {'nLo': 0, 'nLb': 1, 'Eu': 2, 'sub': 3, 'Ea': 4, 'nLa' : 5, 'nEi': 6, 'nLi' : 7, 'nLr' : 8, 'nCE' : 9, 'nLmd' : 10, 'nLma' : 11, 'Lp' : 12, 'Ep' : 13, 'Cp' : 14}
uio_dict = {'ready_for_ui' : 1, 'done_load' : 2, 'CF' : 3, 'ZF' : 4, 'HF' : 5}

async def check_adder_operation(operation, a, b):
    if operation == 0:
        expVal = (a + b) 
        expCF = int((expVal & 0x100) >> 8)
        expVal = expVal & 0xFF  # 8-bit overflow behavior for addition
    elif operation == 1:
        expVal = (a + ((b ^ 0xFF) + 1))
        expCF = (expVal & 0x100) >> 8
        expVal = expVal & 0xFF  # 8-bit underflow behavior for subtraction
    expZF = int(expVal == 0)
    return expVal, expCF, expZF

def setbit(current, bit_index, bit_value):
    modified = current
    if LocalTest:
        modified[bit_index] = bit_value
    else:
        modified[7-bit_index] = bit_value
    return modified
def retrieve_control_signal(control_signal_vals, index):
    # Local testing might use a reverse order, in case we need to modify the order
    if LocalTest:
        return control_signal_vals[index]
    else:
        return control_signal_vals[14-index]
def retrieve_bit_from_8_wide_wire(wire, index):
    # Local testing might use a reverse order, in case we need to modify the order
    if LocalTest:
        return wire[index]
    else:
        return wire[7-index]
    
async def wait_until_next_t0_gltest(dut):
    if (not GLTEST):
        timeout = 0
        dut._log.info("Wait until next T0 in non-GLTEST")
        while not (dut.user_project.cb.stage.value == 5):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 7):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant wait until next T0 in GLTEST")


async def determine_gltest(dut):
    global GLTEST
    dut._log.info("See if the test is being run for GLTEST")
    if hasattr(dut, 'VPWR'):
        dut._log.info(f"VPWR is Defined, may not equal to 1, VPWR={dut.VPWR.value}, GLTEST=TRUE")
        GLTEST = True
    else:
        GLTEST = False
        dut._log.info("VPWR is NOT Defined, GLTEST=False")
        assert dut.user_project.bus.value == dut.user_project.bus.value, "Something went terribly wrong"

async def log_control_signals(dut):
    if (GLTEST):
        dut._log.error("GLTEST is TRUE, can't get control signals")
    else:
        control_signal_vals = dut.user_project.control_signals.value
        dut._log.info(f"Control Signals Array={control_signal_vals}")
        result_string = ""
        for signal in signal_dict:
            result_string += f"{signal}={retrieve_control_signal(control_signal_vals, signal_dict[signal])}, "
        dut._log.info(result_string)

async def log_uio_out(dut):
    uio_vals = dut.uio_out.value
    dut._log.info(f"UIO_OUT Array={uio_vals}")
    result_string = ""
    for uio_pin in uio_dict:
        result_string += f"{uio_pin}={retrieve_bit_from_8_wide_wire(uio_vals, uio_dict[uio_pin])}, "
    dut._log.info(result_string)

async def init(dut):
    dut._log.info("Beginning Initialization")
    # Need to coordinate how we initialize
    await determine_gltest(dut)
    if (GLTEST):
        dut._log.info("GLTEST is TRUE")
    else:
        dut._log.info("GLTEST is FALSE")
    
    dut._log.info(f"Initialize clock with period={CLOCK_PERIOD}{CLOCK_UNITS}")
    clock = Clock(dut.clk, CLOCK_PERIOD, units=CLOCK_UNITS)
    cocotb.start_soon(clock.start())

    dut.ui_in.value = 0
    dut.uio_in.value = 0

    dut._log.info("Enable")
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.ena.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut._log.info("Reset")
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert dut.rst_n.value == 0, f"Reset is not 0, rst_n={dut.rst_n.value}"
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    dut._log.info("Initialization Complete")

async def load_ram(dut, data):
    dut._log.info("RAM Load Start")
    assert len(data) == 16, f"Data length is not 16, len(data)={len(data)}"
    dut.uio_in.value = setbit(dut.uio_in.value, 0, 1) # Start programming
    dut._log.info("Reset")
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for i in range(0, 16):
        timeout = 0
        while not (retrieve_bit_from_8_wide_wire(dut.uio_out.value, uio_dict['ready_for_ui'])):
            await RisingEdge(dut.clk)
            timeout += 1
            if (timeout > 100):
                assert False, (f"Timeout at Byte {i}")
        dut._log.info(f"Loading Byte {i}")
        dut.ui_in.value = data[i]
        timeout = 0
        while not (retrieve_bit_from_8_wide_wire(dut.uio_out.value, uio_dict['done_load'])):
            await RisingEdge(dut.clk)
            if (timeout > 100):
                assert False, (f"Timeout at Byte {i}")
    dut.uio_in.value = setbit(dut.uio_in.value, 0, 0) # Stop programming
    dut._log.info("RAM Load Complete")
    dut._log.info("Reset")
    await RisingEdge(dut.clk)
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    assert dut.rst_n.value == 0, f"Reset is not 0, rst_n={dut.rst_n.value}"
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def dumpRAM(dut):
    dut._log.info("Dumping RAM")
    if (not GLTEST):
        for i in range(0,16):
            if (LocalTest):
                dut._log.info(f"RAM[{i}] = {dut.user_project.ram.RAM.value[i]}")
            else:
                dut._log.info(f"RAM[{i}] = {dut.user_project.ram.RAM.value[15-i]}")
    else:
        dut._log.error("Cant dump RAM in GLTEST")
    dut._log.info("RAM dump complete")

async def mem_check(dut, data):
    dut._log.info("Memory Check Start")
    if (not GLTEST):
        for i in range(0, 16):
            if(LocalTest):
                assert dut.user_project.ram.RAM.value[i] == data[i], f"RAM[{i}] is not equal to data[{i}], RAM[{i}]={dut.user_project.ram.RAM.value[i]}, data[{i}]={data[i]}"
            else:
                assert dut.user_project.ram.RAM.value[15-i] == data[i], f"RAM[{i}] is not equal to data[{i}], RAM[{i}]={dut.user_project.ram.RAM.value[15-i]}, data[{i}]={data[i]}"
    else:
        dut._log.error("Cant check memory in GLTEST")
    dut._log.info("Memory Check Complete")

@cocotb.test()
async def check_gl_test(dut):
    dut._log.info("Checking if the test is being run for GLTEST")
    await determine_gltest(dut)

@cocotb.test()
async def empty_ram_test(dut):
    dut._log.info("Empty RAM Test Start")
    await init(dut)
    await log_control_signals(dut)
    await RisingEdge(dut.clk)
    await ClockCycles(dut.clk, 10)
    dut._log.info("Empty RAM Test Complete")

@cocotb.test()
async def load_ram_test(dut):
    program_data = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    dut._log.info(f"RAM Load Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    dut._log.info("RAM Load Test Complete")

@cocotb.test()
async def output_basic_test(dut):
    program_data = [0x4F, 0x50, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xAB]
    dut._log.info(f"Output Basic Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    for i in range(0, 20):
        dut._log.info(dut.uo_out.value)
        await ClockCycles(dut.clk, 2)
    ##
    dut._log.info("Output Basic Test Complete")
    

@cocotb.test()
async def test_control_signals_execution(dut):
    program_data = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    dut._log.info(f"Control Signals during Execution Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)

    for i in range(0, 20):
        dut._log.info(dut.uo_out.value)
        await ClockCycles(dut.clk, 2)
    ##
    dut._log.info("Control Signals during Execution Test Complete")

async def hlt_checker(dut):
    dut._log.info("HLT Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert retrieve_control_signal(dut.user_project.control_signals.value, 14) == 0, f"""Cp is not 0, Ep={retrieve_control_signal(dut.user_project.control_signals.value, 14)}"""
        assert retrieve_bit_from_8_wide_wire(dut.uio_out.value, uio_dict['HF']) == 1, f"""HF is not 1, HF={retrieve_bit_from_8_wide_wire(dut.uio_out.value, uio_dict['HF'])}"""
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.cb.opcode.value == 0, f"Opcode is not HLT, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert pc_beginning == dut.user_project.pc.counter.value, f"PC is not the same, pc_beginning={pc_beginning}, pc={dut.user_project.pc.counter.value}"

    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check HLT in GLTEST")
    dut._log.info("HLT Checker Complete")

async def nop_checker(dut):
    dut._log.info(f"NOP Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.cb.opcode.value == 1, f"Opcode is not NOP, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check NOP in GLTEST")
    dut._log.info("NOP Checker Complete")

async def add_checker(dut, address):
    dut._log.info(f"ADD Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        val_a = dut.user_project.accumulator_object.regA.value
        if LocalTest:
            val_b = dut.user_project.ram.RAM.value[address]
        else:
            val_b = dut.user_project.ram.RAM.value[15-address]
        expVal, expCF, expZF = await check_adder_operation(0, int(val_a), int(val_b))
        dut._log.info(f"Adder Operation: {int(val_a)} + {int(val_b)} = {expVal}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"Adder Operation bin: {int(val_a):8b} + {int(val_b):8b} = {expVal:8b}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"Adder Operation hex: {int(val_a):02X} + {int(val_b):02X} = {expVal:02X}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000011110100011"), f"Control Signals are not correct, expected=000011110100011"
        assert dut.user_project.cb.opcode.value == 2, f"Opcode is not ADD, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110111100001"), f"Control Signals are not correct, expected=000110111100001"
        assert dut.user_project.input_mar_register.addr.value == address, f"Address in MAR is not correct, mar_address={dut.user_project.input_mar_register.addr.value}, expected={address}"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111000111"), f"Control Signals are not correct, expected=000111111000111"
        assert dut.user_project.b_register.value.value == val_b, f"Value in B Register is not correct, b_register={dut.user_project.b_register.regB.value}, expected={val_b}"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.alu_object.CF.value == expCF, f"Carry Out in ALU is not correct, alu_carry_out={dut.user_project.alu_object.CF.value}, expected={expCF}"
        assert dut.user_project.alu_object.ZF.value == expZF, f"Zero Flag in ALU is not correct, alu_zero_flag={dut.user_project.alu_object.ZF.value}, expected={expZF}"
        assert dut.user_project.accumulator_object.regA.value == expVal, f"Value in Accumulator is not correct, accumulator={dut.user_project.accumulator_object.regA.value}, expected={expVal}"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check ADD in GLTEST")
    dut._log.info("ADD Checker Complete")

async def sub_checker(dut, address):
    dut._log.info(f"SUB Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        val_a = dut.user_project.accumulator_object.regA.value
        if LocalTest:
            val_b = dut.user_project.ram.RAM.value[address]
        else:
            val_b = dut.user_project.ram.RAM.value[15-address]
        expVal, expCF, expZF = await check_adder_operation(1, int(val_a), int(val_b))
        dut._log.info(f"Adder Operation: {int(val_a)} - {int(val_b)} = {expVal}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"Adder Operation bin: {int(val_a):8b} - {int(val_b):8b} = {expVal:8b}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"Adder Operation hex: {int(val_a):02X} - {int(val_b):02X} = {expVal:02X}, CF={expCF}, ZF={expZF}")
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000011110100011"), f"Control Signals are not correct, expected=000011110100011"
        assert dut.user_project.cb.opcode.value == 3, f"Opcode is not SUB, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110111100001"), f"Control Signals are not correct, expected=000110111100001"
        assert dut.user_project.input_mar_register.addr.value == address, f"Address in MAR is not correct, mar_address={dut.user_project.input_mar_register.addr.value}, expected={address}"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111001111"), f"Control Signals are not correct, expected=000111111001111"
        assert dut.user_project.b_register.value.value == val_b, f"Value in B Register is not correct, b_register={dut.user_project.b_register.regB.value}, expected={val_b}"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.alu_object.CF.value == expCF, f"Carry Out in ALU is not correct, alu_carry_out={dut.user_project.alu_object.CF.value}, expected={expCF}"
        assert dut.user_project.alu_object.ZF.value == expZF, f"Zero Flag in ALU is not correct, alu_zero_flag={dut.user_project.alu_object.ZF.value}, expected={expZF}"
        assert dut.user_project.accumulator_object.regA.value == expVal, f"Value in Accumulator is not correct, accumulator={dut.user_project.accumulator_object.regA.value}, expected={expVal}"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check SUB in GLTEST")
    dut._log.info("SUB Checker Complete")

async def lda_checker(dut, address):
    dut._log.info(f"LDA Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        if LocalTest:
            new_val_a = dut.user_project.ram.RAM.value[address]
        else:
            new_val_a = dut.user_project.ram.RAM.value[15-address]
        pc_beginning = dut.user_project.pc.counter.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000011110100011"), f"Control Signals are not correct, expected=000011110100011"
        assert dut.user_project.cb.opcode.value == 4, f"Opcode is not LDA, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110111000011"), f"Control Signals are not correct, expected=000110111000011"
        assert dut.user_project.input_mar_register.addr.value == address, f"Address in MAR is not correct, mar_address={dut.user_project.input_mar_register.addr.value}, expected={address}"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.accumulator_object.regA.value == new_val_a, f"Value in Accumulator is not correct, accumulator={dut.user_project.accumulator_object.regA.value}, expected={new_val_a}"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.accumulator_object.regA.value == new_val_a, f"Value in Accumulator is not correct, accumulator={dut.user_project.accumulator_object.regA.value}, expected={new_val_a}"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check LDA in GLTEST")
    dut._log.info("LDA Checker Complete")

async def out_checker(dut):
    dut._log.info(f"OUT Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        val_a = dut.user_project.accumulator_object.regA.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111110010"), f"Control Signals are not correct, expected=000111111110010"
        assert dut.user_project.cb.opcode.value == 5, f"Opcode is not OUT, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.user_project.output_register.value.value == val_a, f"Value in Output Register is not correct, output_register={dut.output_register.regO.value}, expected={val_a}"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        assert dut.uo_out.value == val_a, f"Value in UO_OUT is not correct, uo_out={dut.uo_out.value}, expected={val_a}"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check OUT in GLTEST")
    dut._log.info("OUT Checker Complete")

async def sta_checker(dut, address):
    dut._log.info(f"STA Checker Start")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        val_a = dut.user_project.accumulator_object.regA.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000011110100011"), f"Control Signals are not correct, expected=000011110100011"
        assert dut.user_project.cb.opcode.value == 6, f"Opcode is not STA, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000101111110011"), f"Control Signals are not correct, expected=000101111110011"
        assert dut.user_project.input_mar_register.addr.value == address, f"Address in MAR is not correct, mar_address={dut.user_project.input_mar_register.addr.value}, expected={address}"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111011100011"), f"Control Signals are not correct, expected=000111011100011"
        assert dut.user_project.input_mar_register.data.value == val_a, f"Value in MAR is not correct, mar_data={dut.user_project.input_ram_register.data.value}, expected={val_a}"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        if LocalTest:
            assert dut.user_project.ram.RAM.value[address] == val_a, f"Value in RAM is not correct, ram={dut.user_project.ram.RAM.value[address]}, expected={val_a}"
        else:
            assert dut.user_project.ram.RAM.value[15-address] == val_a, f"Value in RAM is not correct, ram={dut.user_project.ram.RAM.value[15-address]}, expected={val_a}"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == (int(pc_beginning)+1)%16, f"PC is not incremented, pc={dut.user_project.pc.counter.value}, pc_beginning={pc_beginning}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check STA in GLTEST")
    dut._log.info("STA Checker Complete")

async def jmp_checker(dut, address):
    dut._log.info(f"JMP Checker Start with jmp_address={address}, hex={address:01X}, bin={address:4b}")
    if (not GLTEST):
        timeout = 0
        while not (dut.user_project.cb.stage.value == 0):
            await RisingEdge(dut.clk)
            dut._log.info(f"Stage={dut.user_project.cb.stage.value}")
            timeout += 1
            if (timeout > 2):
                assert False, (f"Timeout at {dut.user_project.pc.counter.value}")
        pc_beginning = dut.user_project.pc.counter.value
        dut._log.info(f"PC={pc_beginning}")
        dut._log.info("T0")
        assert dut.user_project.cb.stage.value == 0, f"Stage is not 0, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("010011111100011"), f"Control Signals are not correct, expected=010011111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T1")
        assert dut.user_project.cb.stage.value == 1, f"Stage is not 1, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("100111111100011"), f"Control Signals are not correct, expected=100111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T2")
        assert dut.user_project.cb.stage.value == 2, f"Stage is not 2, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000110101100011"), f"Control Signals are not correct, expected=000110101100011"
        await RisingEdge(dut.clk)
        dut._log.info("T3")
        assert dut.user_project.cb.stage.value == 3, f"Stage is not 3, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("001111110100011"), f"Control Signals are not correct, expected=001111110100011"
        assert dut.user_project.cb.opcode.value == 7, f"Opcode is not JMP, opcode={dut.user_project.cb.opcode.value}"
        await RisingEdge(dut.clk)
        dut._log.info("T4")
        assert dut.user_project.cb.stage.value == 4, f"Stage is not 4, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T5")
        assert dut.user_project.cb.stage.value == 5, f"Stage is not 5, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info("T6")
        assert dut.user_project.cb.stage.value == 6, f"Stage is not 6, stage={dut.user_project.cb.stage.value}"
        await log_control_signals(dut)
        await log_uio_out(dut)
        assert dut.user_project.control_signals.value == LogicArray("000111111100011"), f"Control Signals are not correct, expected=000111111100011"
        await RisingEdge(dut.clk)
        dut._log.info(f"PC={dut.user_project.pc.counter.value}")
        assert dut.user_project.pc.counter.value == address, f"PC is not address, pc={dut.user_project.pc.counter.value}, jmp_address={address}"
    else:
        for i in range(7):
            await RisingEdge(dut.clk)
        dut._log.error("Cant check JMP in GLTEST")
    dut._log.info("JMP Checker Complete")


@cocotb.test()
async def test_operation_hlt(dut):
    program_data = [0x0F, 0x0F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    dut._log.info(f"Operation HLT Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    await hlt_checker(dut)
    dut._log.info("Operation HLT Test Complete")

@cocotb.test()
async def test_operation_jmp(dut):
    program_data = [0x7E, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0F]
    dut._log.info(f"Operation JMP Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await jmp_checker(dut, program_data[0]&0xF)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    await hlt_checker(dut)
    dut._log.info("Operation JMP Test Complete")

@cocotb.test()
async def test_operation_nop(dut):
    program_data = [0x1E, 0x1F, 0x70, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0F]
    dut._log.info(f"Operation NOP Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await nop_checker(dut)
    await nop_checker(dut)
    await jmp_checker(dut, program_data[2]&0xF)
    await nop_checker(dut)
    dut._log.info("Operation NOP Test Complete")

@cocotb.test()
async def test_operation_add(dut):
    program_data = [0x2E, 0x10, 0x70, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation ADD Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await add_checker(dut, program_data[0]&0xF)
    await nop_checker(dut)
    await jmp_checker(dut, program_data[2]&0xF)
    await add_checker(dut, program_data[0]&0xF)
    dut._log.info("Operation ADD Test Complete")

@cocotb.test()
async def test_operation_add_2(dut):
    program_data = [0x2E, 0x10, 0x70, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xA9, 0xFF]
    dut._log.info(f"Operation ADD 2 Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await add_checker(dut, program_data[0]&0xF)
    await nop_checker(dut)
    await jmp_checker(dut, program_data[2]&0xF)
    await add_checker(dut, program_data[0]&0xF)
    dut._log.info("Operation ADD 2 Test Complete")


@cocotb.test()
async def test_operation_sub(dut):
    program_data = [0x3E, 0x10, 0x70, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation SUB Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await sub_checker(dut, program_data[0]&0xF)
    await nop_checker(dut)
    await jmp_checker(dut, program_data[2]&0xF)
    await sub_checker(dut, program_data[0]&0xF)
    dut._log.info("Operation SUB Test Complete")

@cocotb.test()
async def test_operation_sub_add(dut):
    program_data = [0x3E, 0x10, 0x2E, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation SUB ADD Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await sub_checker(dut, program_data[0]&0xF)
    await nop_checker(dut)
    await add_checker(dut, program_data[0]&0xF)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    await hlt_checker(dut)
    await hlt_checker(dut)
    dut._log.info("Operation SUB ADD Test Complete")

@cocotb.test()
async def test_operation_lda(dut):
    program_data = [0x4E, 0x2F, 0x1F, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation LDA Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await lda_checker(dut, program_data[0]&0xF)
    await add_checker(dut, program_data[1]&0xF)
    await nop_checker(dut)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    dut._log.info("Operation LDA Test Complete")

@cocotb.test()
async def test_operation_out(dut):
    program_data = [0x4E, 0x2F, 0x5F, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation OUT Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await lda_checker(dut, program_data[0]&0xF)
    await add_checker(dut, program_data[1]&0xF)
    await out_checker(dut)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    dut._log.info("Operation OUT Test Complete")

@cocotb.test()
async def test_operation_sta(dut):
    program_data = [0x4E, 0x2F, 0x5F, 0x60, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x09, 0xFF]
    dut._log.info(f"Operation STA Test Start")
    dut._log.info(f"data_bin={[str(bin(x)) for x in program_data]}")
    dut._log.info(f"data_hex={[str(hex(x)) for x in program_data]}")
    await init(dut)
    await load_ram(dut, program_data)
    await dumpRAM(dut)
    await mem_check(dut, program_data)
    await lda_checker(dut, program_data[0]&0xF)
    await add_checker(dut, program_data[1]&0xF)
    await out_checker(dut)
    await sta_checker(dut, program_data[3]&0xF)
    await wait_until_next_t0_gltest(dut)
    await hlt_checker(dut)
    await dumpRAM(dut)
    dut._log.info("Operation STA Test Complete")