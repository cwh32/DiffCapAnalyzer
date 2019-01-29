import glob
from math import isclose
import numpy as np
import os
import pandas as pd
from pandas import ExcelWriter
import requests
import scipy.io
import scipy.signal
#import pandas.io.sql as pd_sql
#import sqlite3 as sql



############################
# Sub - Wrapper Functions
############################


def load_sep_cycles(file_name, database_name):
    """Get data from a specified file, separates out data into
    cycles and saves those cycles as .xlsx files in specified
    filepath (must be an existing folder)"""
    df_single = pd.read_excel(file_name,1)
    gb = df_single.groupby(by=['Cycle_Index'])
    cycle_dict = dict(iter(gb))
    battname = file_name.split('.')[0]
    for i in range(1, len(cycle_dict)+1):
    	cycle_dict[i]['Battery_Label'] = battname
    for i in range(1, len(cycle_dict)+1):
    	update_database_newtable(cycle_dict[i], battname+'-'+'Cycle'+ str(i), database_name)
    print('All data separated into cycles and saved in database.')
    return cycle_dict




def get_clean_cycles(cycle_dict, file_name, database_name):
    """Imports all separated out cycles in given path and cleans them
    and saves them in the specified filepath"""
    name = file_name.split('.')[0]
    clean_cycle_dict = {} 
    for i in range(1, len(cycle_dict)+1):
    	charge, discharge = clean_calc_sep_smooth(cycle_dict[i], 9, 3)
    	clean_data = discharge.append(charge, ignore_index=True)
    	clean_data = clean_data.reset_index(drop=True)
    	cyclename = name + '-CleanCycle' + str(i)
    	#print(cyclename)
    	clean_cycle_dict.update({cyclename : clean_data})
    	update_database_newtable(clean_data, cyclename, database_name)
    	#run the peak finding peak fitting part here 
    #for key in clean_cycle_dict:
    #	print(key)
    print('All cycles cleaned and saved in database')
    return clean_cycle_dict


def get_clean_sets(clean_cycle_dict, file_name, database_name):
    """Imports all clean cycles of data from import path and appends
    them into complete sets of battery data, saved into save_filepath"""
    clean_set_df = pd.DataFrame()
    name = file_name.split('.')[0]
    for key, value in clean_cycle_dict.items():
    	clean_set_df.append(value, ignore_index = True)

    #clean_set_df = clean_set_df.sort_values(['Data_Point'], ascending = True)
    clean_set_df.reset_index(drop = True)
    
    update_database_newtable(clean_set_df, name + 'CleanSet', database_name)
    
    print('All clean cycles recombined and saved in database')
    return clean_set_df

############################
# Component Functions
############################

def clean_calc_sep_smooth(dataframe, windowlength, polyorder):
    """Takes one cycle dataframe, calculates dq/dv, cleans the data,
    separates out charge and discharge, and applies sav-golay filter.
    Returns two dataframes, one charge and one discharge.
    Windowlength and polyorder are for the sav-golay filter."""
    assert type(dataframe) == pd.DataFrame
    df = init_columns(dataframe)
    df1 = calc_dq_dqdv(df)
    raw_charge = df1[df1['Current(A)'] > 0]
    raw_charge = raw_charge.reset_index(drop=True)
    # this separated out the charging data and put it in 'raw_charge'.
    # Reset the index as well.

    raw_discharge = df1[df1['Current(A)'] < 0]
    raw_discharge = raw_discharge.reset_index(drop=True)
    # this separated out the discharging data and put it in 'raw_discharge'.
    # Reset the index as well.

    clean_charge2 = drop_0_dv(raw_charge, 'c')
    clean_discharge2 = drop_0_dv(raw_discharge, 'd')
    # apply the drop_0_dv function to clean out the wonky data points,
    # especially near the voltage corresponding to the end of a cycle.

    clean_charge2 = clean_charge2.sort_values(['Voltage(V)'], ascending=True)
    clean_discharge2 = clean_discharge2.sort_values(
        ['Voltage(V)'], ascending=False)
    # sorted the values because sometimes the data points are out of order,
    # especially in the first cycle of a battery.

    cleandf2 = clean_charge2.append(clean_discharge2, ignore_index=True)
    cleandf2 = cleandf2.reset_index(drop=True)
    # appends the clean charge and discharge cycles to get a full set of
    # clean data. Reset the index as well.

    charge, discharge = sep_char_dis(cleandf2)
    # apply the sep_char_dis function to cleandf2. This is necessary
    # because the sep_char_dis function actually assigns the values of
    # dq/dv to use. The discharge cycles need dq/dv to be calculated
    # based on the discharge capacity, and the charge cycles need
    # dq/dv to be calculated based on the charge capacity. This structure
    # could probably be improved since we are separating out charge/discharge,
    # then recombining, then separating again, then recombining.

    if len(discharge) > windowlength:
        smooth_discharge = my_savgolay(discharge, windowlength, polyorder)
    else:
        discharge['Smoothed_dQ/dV'] = discharge['dQ/dV']
        smooth_discharge = discharge
    # this if statement is for when the datasets have less datapoints
    # than the windowlength given to the sav_golay filter.
    # without this if statement, the sav_golay filter throws an error
    # when given a dataset with too few points. This way, we simply
    # forego the smoothing function.
    if len(charge) > windowlength:
        smooth_charge = my_savgolay(charge, windowlength, polyorder)
    else:
        charge['Smoothed_dQ/dV'] = charge['dQ/dV']
        smooth_charge = charge
    # same as above, but for charging cycles.
    return smooth_charge, smooth_discharge



def init_columns(cycle_df):
    """This function calculates the dv and the dq/dv for a dataframe."""
    assert type(cycle_df) == pd.DataFrame
    assert 'Voltage(V)' in cycle_df.columns
    assert 'Discharge_Capacity(Ah)' in cycle_df.columns
    assert 'Charge_Capacity(Ah)' in cycle_df.columns

    cycle_df = cycle_df.reset_index(drop=True)
    cycle_df['dV'] = None
    cycle_df['Discharge_dQ'] = None
    cycle_df['Charge_dQ'] = None
    cycle_df['Discharge_dQ/dV'] = None
    cycle_df['Charge_dQ/dV'] = None
    return cycle_df

def calc_dq_dqdv(cycle_df):
	for i in range(1, len(cycle_df)):
        cycle_df.loc[i, ('dV')] = cycle_df.loc[i, ('Voltage(V)')
                                               ] - cycle_df.loc[i-1, ('Voltage(V)')]
        cycle_df.loc[i, ('Discharge_dQ')] = cycle_df.loc[i, ('Discharge_Capacity(Ah)')
                                                         ] - cycle_df.loc[i-1, ('Discharge_Capacity(Ah)')]
        cycle_df.loc[i, ('Charge_dQ')] = cycle_df.loc[i, ('Charge_Capacity(Ah)')
                                                      ] - cycle_df.loc[i-1, ('Charge_Capacity(Ah)')]
    cycle_df['Discharge_dQ/dV'] = cycle_df['Discharge_dQ']/cycle_df['dV']
    cycle_df['Charge_dQ/dV'] = cycle_df['Charge_dQ']/cycle_df['dV']
    return cycle_df

def drop_0_dv(cycle_df_dv, cd):
    '''Drop rows where dv=0 (or about 0) in a dataframe that has
    already had dv calculated. Then recalculate dv and calculate dq/dv'''
    # this will clean up the data points around V = 4.2V
    # (since they are holding voltage at 4.2V for a while).
    assert 'dV' in cycle_df_dv.columns
    assert 'Current(A)' in cycle_df_dv.columns

    cycle_df_dv = cycle_df_dv.reset_index(drop=True)

    cycle_df_dv['dv_close_to_zero'] = None

    #dropping values where current = 0
    # change to dq/dv = 0 

    for i in range(1, len(cycle_df_dv)):
        if isclose(cycle_df_dv.loc[i, ('Current(A)')], 0, abs_tol=10**-3):
            cycle_df_dv = cycle_df_dv.drop(index=i)

    cycle_df_dv = cycle_df_dv.reset_index(drop=True)
    switch_cd_index = np.where(np.diff(np.sign(cycle_df_dv['Current(A)'])))
    for i in switch_cd_index:
        cycle_df_dv = cycle_df_dv.drop(cycle_df_dv.index[i+1])

    cycle_df_dv = cycle_df_dv.reset_index(drop=True)

 #   for i in range(1, len(cycle_df_dv)):
 #       if isclose(cycle_df_dv.loc[i, ('dV')], 0, abs_tol=10**-3):
 #           # was -3.5 before
 #           cycle_df_dv.loc[i, ('dv_close_to_zero')] = False
 #       else:
 #           cycle_df_dv.loc[i, ('dv_close_to_zero')] = True

#    while (False in cycle_df_dv['dv_close_to_zero'].values or
#           cycle_df_dv['dV'].max() > 0.7 or cycle_df_dv['dV'].min() < -0.7):

 #       cycle_df_dv = cycle_df_dv.reset_index(drop=True)

    for i in range(1, len(cycle_df_dv)):
       if isclose(cycle_df_dv.loc[i, ('dV')], 0, abs_tol=10**-3):
           cycle_df_dv = cycle_df_dv.drop(index=i)

    cycle_df_dv = cycle_df_dv.reset_index(drop=True)

    if cd == 'c':
        #if we are looking at the charge cycle
        for i in range(1, len(cycle_df_dv)):
           if isclose(cycle_df_dv.loc[i, ('Charge_dQ')], 0, abs_tol=10**-3):
               cycle_df_dv = cycle_df_dv.drop(index=i)

        cycle_df_dv = cycle_df_dv.reset_index(drop=True)
    if cd == 'd':
    #if we are looking at the discharge cycle
        for i in range(1, len(cycle_df_dv)):
           if isclose(cycle_df_dv.loc[i, ('Discharge_dQ')], 0, abs_tol=10**-3):
               cycle_df_dv = cycle_df_dv.drop(index=i)
        cycle_df_dv = cycle_df_dv.reset_index(drop=True)
 #       separate_dis_char = np.where(
  #          np.diff(np.sign(cycle_df_dv['Current(A)'])))

   #     for i in range(1, len(cycle_df_dv)):
    #        if (cycle_df_dv.loc[i, ('dV')] > 0.7 or cycle_df_dv.loc[i, ('dV')] < -0.7):
     #           cycle_df_dv = cycle_df_dv.drop(index=i)

#        cycle_df_dv = cycle_df_dv.reset_index(drop=True)

        # for i in range(1, len(cycle_df_dv)):
        #     cycle_df_dv.loc[i, ('dV')] = cycle_df_dv.loc[i,
        #                                                  ('Voltage(V)')] - cycle_df_dv.loc[i-1, ('Voltage(V)')]
        #     if isclose(cycle_df_dv.loc[i, ('dV')], 0, abs_tol=10**-3):
        #         cycle_df_dv.loc[i, ('dv_close_to_zero')] = False
        #     else:
        #         cycle_df_dv.loc[i, ('dv_close_to_zero')] = True

        # cycle_df_dv = cycle_df_dv.reset_index(drop=True)

   # cycle_df_dv = cycle_df_dv.reset_index(drop=True)

    # recalculating dv and dq's after dropping rows
    calc_dq_dqdv(cycle_df_dv)

    cycle_df_dv = cycle_df_dv.dropna(subset=['Discharge_dQ/dV'])
    cycle_df_dv = cycle_df_dv.dropna(subset=['Charge_dQ/dV'])
    cycle_df_dv = cycle_df_dv.reset_index(drop=True)

    cycle_df_dv = cycle_df_dv.reset_index(drop=True)
    print('cycle cleaned NLT')
    return cycle_df_dv


def sep_char_dis(df_dqdv):
    '''Takes a dataframe of one cycle with calculated dq/dv and
    separates into charge and discharge differential capacity curves'''
    assert 'Charge_dQ/dV' in df_dqdv.columns
    assert 'Discharge_dQ/dV' in df_dqdv.columns
    charge = df_dqdv[df_dqdv['Current(A)'] > 0]
    charge.is_copy = None
    charge = charge.reset_index(drop=True)
    charge['dQ/dV'] = charge['Charge_dQ/dV']

    for i in range(1, len(charge)):
        if charge.loc[i, ('dQ/dV')] == 0:
            charge = charge.drop(index=i)
    charge = charge.reset_index(drop=True)

    discharge = df_dqdv[df_dqdv['Current(A)'] < 0]
    discharge.is_copy = None
    discharge['dQ/dV'] = discharge['Discharge_dQ/dV']
    discharge = discharge.reset_index(drop=True)

    for i in range(1, len(discharge)):
        if discharge.loc[i, ('dQ/dV')] == 0:
            discharge = discharge.drop(index=i)
    discharge = discharge.reset_index(drop=True)

    return charge, discharge


def my_savgolay(dataframe, windowlength, polyorder):
    """Takes battery dataframe with a dQ/dV column and applies a
    sav_golay filter to it, returning the dataframe with a new
    column called Smoothed_dQ/dV"""
    assert not windowlength % 2 == 0
    # asserts this is an odd number - necessary to run the
    # savgol_filter function
    assert polyorder < windowlength
    # necessary to run the savgol_filter function as well.
    unfilt = pd.concat([dataframe['dQ/dV']])
    unfiltar = unfilt.values
    # converts into an array
    dataframe['Smoothed_dQ/dV'] = scipy.signal.savgol_filter(
        unfiltar, windowlength, polyorder)
    # had windowlength = 21 and polyorder = 3 before
    return dataframe

#init_master_table()
#process_data('CS2_33_10_04_10.xlsx', 'nlt_test_demo.db')