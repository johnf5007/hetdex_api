# -*- coding: utf-8 -*-
"""
Created: 2019/01/25

@author: Erin Mentuch Cooper

This file contains all information related to the HETDEX line detections
catalog

Updated: 2020/06/03

Updated to read in Karl's new detection output that is organized by shot + amp


Examples
--------

To create for a month:

>>> python3 create_detect_hdf5.py -m 201901 -of detect_201901.h5

Then once all months are done, merge into one file:

>>> python3 create_detect_hdf5.py --merge -of detect_hdr2.h5

To run continuum sources, use create_cont_hdf5.py instead

"""
from __future__ import print_function

import sys
import os
import os.path as op
import argparse as ap
import re
import glob
import subprocess
import numpy as np
import tables as tb

from astropy.coordinates import SkyCoord
from astropy.io import ascii
from astropy.io import fits
from astropy.table import Table, vstack
import astropy.units as u
from hetdex_api.input_utils import setup_logging
from hetdex_api.config import HDRconfig

import warnings
warnings.filterwarnings('ignore')

def get_detectname(ra, dec):
    """
    convert ra,dec coordinates to a IAU-style object name.
    """
    coord = SkyCoord(ra*u.deg, dec*u.deg)
    
    return "HETDEX J{0}{1}".format(
        coord.ra.to_string(unit=u.hourangle, sep="", precision=2, pad=True),
        coord.dec.to_string(sep="", precision=1, alwayssign=True, pad=True))


class Detections(tb.IsDescription):
    shotid = tb.Int64Col(pos=2)
    date = tb.Int32Col(pos=5)
    obsid = tb.Int32Col(pos=6)
    detectid = tb.Int64Col(pos=0)
    fiber_id = tb.StringCol((38))
    detectname = tb.StringCol((40))
    ra = tb.Float32Col(pos=3)
    dec = tb.Float32Col(pos=4)
    wave = tb.Float32Col(pos=7)
    wave_err = tb.Float32Col(pos=8)
    flux = tb.Float32Col(pos=9)
    flux_err = tb.Float32Col(pos=10)
    linewidth = tb.Float32Col(pos=11)
    linewidth_err = tb.Float32Col(pos=12)
    continuum = tb.Float32Col(pos=13)
    continuum_err = tb.Float32Col(pos=14)
    sn = tb.Float32Col(pos=15)
    sn_err = tb.Float32Col(pos=16)
    chi2 = tb.Float32Col(pos=17)
    chi2_err = tb.Float32Col(pos=18)
    noise_ratio = tb.Float32Col()
    inputid = tb.StringCol((40))
    x_raw = tb.Int32Col(pos=21)
    y_raw = tb.Int32Col(pos=22)
    x_ifu = tb.Float32Col()
    y_ifu = tb.Float32Col()
    weight = tb.Float32Col()
    fibnum = tb.Int32Col(pos=20)
    multiframe = tb.StringCol((20), pos=19)
    specid = tb.StringCol((3))
    ifuslot = tb.StringCol((3))
    ifuid = tb.StringCol((3))
    amp = tb.StringCol((2))
    expnum = tb.Int32Col()
    chi2fib = tb.Float32Col()

class Spectra(tb.IsDescription):
    detectid = tb.Int64Col(pos=0)
    wave1d = tb.Float32Col(1036, pos=1)
    spec1d = tb.Float32Col(1036, pos=2)
    spec1d_err = tb.Float32Col(1036, pos=3)
    counts1d = tb.Float32Col(1036, pos=4)
    counts1d_err = tb.Float32Col(1036, pos=5)
    apsum_counts = tb.Float32Col(1036, pos=6)
    apsum_counts_err = tb.Float32Col(1036, pos=7)
    spec1d_nc = tb.Float32Col(1036)
    spec1d_nc_err = tb.Float32Col(1036)
    apcor = tb.Float32Col(1036)
    flag_pix = tb.Float32Col(1036)

class Fibers(tb.IsDescription):
    detectid = tb.Int64Col(pos=0)
    ra = tb.Float32Col(pos=1)
    dec = tb.Float32Col(pos=2)
    x_ifu = tb.Float32Col(pos=5)
    y_ifu = tb.Float32Col(pos=6)
    multiframe = tb.StringCol((20), pos=3)
    fibnum = tb.Int32Col()
    fiber_id = tb.StringCol((38), pos=4)
    expnum = tb.Int32Col(pos=9)
    distance = tb.Float32Col(pos=10)
    wavein = tb.Float32Col(pos=12)
    timestamp = tb.StringCol((17), pos=11)
    date = tb.Int32Col(pos=7)
    obsid = tb.Int32Col(pos=8)
    flag = tb.Int32Col(pos=13)
    weight = tb.Float32Col(pos=14)
    ADC = tb.Float32Col((5), pos=15)
    specid = tb.StringCol((3))
    ifuslot = tb.StringCol((3))
    ifuid = tb.StringCol((3))
    amp = tb.StringCol((2))
    x_raw = tb.Int32Col()
    y_raw = tb.Int32Col()


def main(argv=None):
    """ Main Function """
    # Call initial parser from init_utils
    parser = ap.ArgumentParser(description="""Create HDF5 file.""", add_help=True)

    parser.add_argument(
        "-m", "--month", help="""Month to run: 201901""", type=str, default=None
    )

    parser.add_argument(
        "-d",
        "--date",
        help="""Date, e.g., 20170321, YYYYMMDD""",
        type=str,
        default=None,
    )

    parser.add_argument(
        "-o",
        "--observation",
        help='''Observation number, "00000007" or "7"''',
        type=str,
        default=None,
    )

    parser.add_argument(
        "-of",
        "--outfilename",
        type=str,
        help="""Relative or absolute path for output HDF5
                        file.""",
        default=None,
    )

    parser.add_argument(
        "-a",
        "--append",
        help="""Appending to existing detection HDF5 file.""",
        action="count",
        default=0,
    )

    parser.add_argument(
        "-dp",
        "--detect_path",
        help="""Path to detections""",
        type=str,
        default="/data/00115/gebhardt/alldet/output",
    )

    parser.add_argument(
        "-ifu",
        "--ifu",
        help="""IFU to ingest""",
        type=str,
        default=None,
    )
    
    parser.add_argument(
        "-md",
        "--mergedir",
        help="""Merge all HDF5 files in the defined merge 
                        directory. Can append to existing file using --append option""",
        type=str,
        default=os.getcwd(),
    )

    parser.add_argument(
        "--merge",
        "-merge",
        help="""Boolean trigger to merge all 2*.fits files in cwd""",
        default=False,
        required=False,
        action="store_true",
    )

    parser.add_argument(
        "--mergemonth",
        "-mm",
        help=""" Boolean trigger to merge all detect_month*.h5 files""",
        default=False,
        required=False,
        action="store_true",
    )

    parser.add_argument(
        "--broad",
        "-broad",
        help=""" Boolean trigger to select broad sources""",
        default=False,
        required=False,
        action="store_true",
    )

    args = parser.parse_args(argv)
    args.log = setup_logging()

    #check if shotid is in badlist
#    config = HDRconfig(args.survey)
#    badshots = np.loadtxt(config.badshot, dtype=int)

    if args.outfilename:
        outfilename = args.outfilename
    elif args.month and args.merge:
        outfilename = 'detect_month_' + str(args.month) + '.h5'
    else:
        outfilename = 'detect_'+ str(args.date) + str(args.observation).zfill(3) + '.h5'
        
    # Creates a new file if the "--append" option is not set or the file
    # does not already exist.
    
    if args.append:
        fileh = tb.open_file(args.outfilename, "a", "HDR2.1 Detections Database")
        detectidx = np.max(fileh.root.Detections.cols.detectid) + 1
    else:

        if args.broad:
            fileh = tb.open_file(outfilename, "w", "HDR2.1 Broad Detections Database")
            index_buff = 2160000000
#        elif args.continuum:
#            fileh = tb.open_file(outfilename, "w", "HDR2.1 Continuum Source Database")
#            index_buff = 2190000000
        else:
            fileh = tb.open_file(outfilename, "w", "HDR2.1 Detections Database")
            index_buff = 2100000000

        detectidx = index_buff

    if args.merge:

        tableMain = fileh.create_table(
            fileh.root,
            "Detections",
            Detections,
            "HETDEX Line Detection Catalog",
            expectedrows=1000000,
        )
        tableFibers = fileh.create_table(
            fileh.root,
            "Fibers",
            Fibers,
            "Fiber info for each detection",
            expectedrows=15000000,
        )
        tableSpectra = fileh.create_table(
            fileh.root,
            "Spectra",
            Spectra,
            "1D Spectra for each Line Detection",
            expectedrows=1000000,
        )

        if args.month:
            files = sorted(glob.glob(op.join(args.mergedir, "detect_" + str(args.month) + '*.h5')))
        elif args.mergemonth:
            files = sorted(glob.glob( op.join( args.mergedir, "detect_month*.h5")))
        else:
            files = sorted(glob.glob(op.join(args.mergedir, "detect_2*.h5")))

        detectid_max = 0

        for file in files:

            args.log.info("Appending detect H5 file: %s" % file)

            fileh_i = tb.open_file(file, "r")

            tableMain_i = fileh_i.root.Detections.read()

            if np.size(tableMain_i) == 0:
                args.log.error('No detections for %s' % file)
                continue
                
            tableFibers_i = fileh_i.root.Fibers.read()
            tableSpectra_i = fileh_i.root.Spectra.read()

            tableMain_i["detectid"] += detectid_max
            tableFibers_i["detectid"] += detectid_max
            tableSpectra_i["detectid"] += detectid_max

            # after first table be sure to add one to the index
            
            detectid_max = 1
            
            tableMain.append(tableMain_i)
            tableFibers.append(tableFibers_i)
            tableSpectra.append(tableSpectra_i)
            
            detectid_max = np.max(tableMain.cols.detectid[:]) - index_buff + 1 

            fileh_i.close()
            tableFibers.flush()  # just to be safe
            tableSpectra.flush()
            tableMain.flush()

        if args.month:
            ifufiles = sorted( glob.glob( op.join(args.mergedir, "ifustat_" + str(args.month) + "*.tab")))
        elif args.mergemonth:
            ifufiles = sorted( glob.glob( op.join(args.mergedir, "ifustats_month*.tab")))
        else:
            ifufiles = sorted( glob.glob( op.join(args.mergedir, "ifustat_2*.tab")))
        
        ifu_tab = Table()
        
        for ifufile in ifufiles:
            ifu_i = Table.read(ifufile, format='ascii')
            if np.size(ifu_i) > 0:
                ifu_tab = vstack([ifu_tab, ifu_i])
            else:
                args.log.warning('IFU stats file is empty: ' + ifufile)
            
        if args.month:
            ifu_tab.write('ifustats_month_' + str(args.month) + '.tab', format='ascii')
        else:
            ifu_tab.write('ifustats_merged.tab', format='ascii')
 
    else:

        if args.append:
            tableMain = fileh.root.Detections
            tableSpectra = fileh.root.Spectra
            tableFibers = fileh.root.Fibers
        else:
            tableMain = fileh.create_table(
                fileh.root,
                "Detections",
                Detections,
                "HETDEX Line Detection Catalog"
            )
            tableFibers = fileh.create_table(
                fileh.root,
                "Fibers",
                Fibers,
                "Fiber info for each detection"
            )
            tableSpectra = fileh.create_table(
                fileh.root,
                "Spectra",
                Spectra,
                "1D Spectra for each Line Detection"
            )

        
        amp_stats = Table.read('/data/05350/ecooper/hdr2.1/survey/amp_flag.fits')
    
        colnames = ['wave', 'wave_err','flux','flux_err','linewidth','linewidth_err',
                    'continuum','continuum_err','sn','sn_err','chi2','chi2_err','ra','dec',
                    'datevshot','noise_ratio','linewidth_fix','chi2_fix', 'chi2fib',
                    'src_index','multiname', 'exp','xifu','yifu','xraw','yraw','weight']

        if args.date and args.observation:
            mcres_str = str(args.date) + "v" + str(args.observation).zfill(3) + "*mc"
            shotid = int(str(args.date) + str(args.observation).zfill(3))
            amp_stats = amp_stats[amp_stats['shotid'] == shotid]
        elif args.month:
            mcres_str = str(args.month) + "*mc"
            amp_stats['month'] = (amp_stats['shotid']/100000).astype(int)
            amp_stats = amp_stats[amp_stats['month'] == int(args.month)]
        elif args.ifu:
            mcres_str = "*" + args.ifu + ".mc"
        else:
            args.log.warning('Please provide a date(YYYMMDD)+observation or month (YYYYMM')
            sys.exit()

        catfiles =  sorted( glob.glob( op.join( args.detect_path, mcres_str)))

        det_cols = fileh.root.Detections.colnames

        amplist = []
        ndet = []
        ndet_sel = []
        
        for catfile in catfiles:
            
            amp_i = catfile[-27:-3]

            if args.ifu:
                # Fudge to add in V038 for 201701 to 20180915 only
                date_i = int(amp_i[0:8])
                if date_i > 20180915:
                    break
            
            amplist.append(amp_i)

            args.log.info('Ingesting Amp: '+ amp_i)

            ndet_file = sum(1 for line in open(catfile))
            ndet.append( ndet_file)

            if ndet_file == 0:
                ndet_sel.append( 0)
                continue
                
            try:
                detectcatall = Table.read(catfile, format='ascii.no_header', names=colnames)
            except:
                ndet_sel.append( 0)
                args.log.warning('Could not ingest ' + catfile)
                continue

            if args.broad:
                selSN = (detectcatall['sn'] > 5)
                selLW = (detectcatall['linewidth'] > 5)
                selchi2 = (detectcatall['chi2'] > 1.6)
                selcont = (detectcatall['continuum'] >= -3) * (detectcatall['continuum'] <= 8)
                selwave = (detectcatall['wave'] > 3510) * (detectcatall['wave'] < 5480)
                selchi2fib = (detectcatall['chi2fib'] < 5)
                selcat = selSN * selLW * selcont * selwave * selchi2fib
            else:
                selSN = (detectcatall['sn'] > 4.5)
                selLW = (detectcatall['linewidth'] > 1.7)
#                selchi2 = (detectcatall['chi2'] <= 5)
#                selcont = (detectcatall['continuum'] >= -3) * (detectcatall['continuum'] <= 20)
#                selwave = (detectcatall['wave'] > 3510) * (detectcatall['wave'] < 5490)
                selchi2fib = (detectcatall['chi2fib'] < 5)
                selcat = selSN * selLW * selchi2fib

            detectcat = detectcatall[selcat]

            nsel_file = np.sum(selcat)

            try:
                specfile = op.join(args.detect_path, amp_i + ".spec")
                spectable= Table.read(specfile, format="ascii.no_header")
            except:
                args.log.warning('Could not ingest ' + specfile)
                ndet_sel.append( 0)
                continue

            try:
                filefiberinfo = op.join(args.detect_path, amp_i + ".list")
                fibertable = Table.read(filefiberinfo, format="ascii.no_header")
            except:
                args.log.warning('Could not ingest ' + filefiberinfo)
                ndet_sel.append( 0)
                continue

            ndet_sel.append(nsel_file)
                
            for row in detectcat:
            
                inputid_i = amp_i + '_' + str(row['src_index']).zfill(3)

                rowMain = tableMain.row

                rowMain['detectid'] = detectidx
                if args.date and args.observation:
                    rowMain['shotid'] = int(str(args.date) + str(args.observation).zfill(3))
                    rowMain['date'] = int(args.date)
                    rowMain['obsid'] = int(args.observation)
                else:
                    rowMain['date'] = int(amp_i[0:8])
                    rowMain['obsid'] = int(amp_i[9:12])
                    rowMain['shotid'] = int(amp_i[0:8] + amp_i[9:12])

                # check if amp is in bad amp list
                multiframe = row['multiname'][0:20]

                if multiframe in ['multi_051_105_051_RL', 'multi_051_105_051_RU']:
                    if (row['wave'] > 3540) and (row['wave'] < 3560):
                        continue

                if multiframe in ['multi_032_094_028_RU']:
                    if (row['wave'] > 3530) and (row['wave'] < 3545):
                        continue
                        
                selamp = (amp_stats['shotid'] == rowMain['shotid']) * (amp_stats['multiframe'] == multiframe)
                ampflag = amp_stats['flag'][selamp]
                
                if np.size(ampflag) == 0:
                    args.log.error('No ampflag for '
                                   + str(rowMain['shotid'])
                                   + ' ' + multiframe)
                    
                if ampflag==False:
                    continue

                # check if Karl stored the same fiber as me:
                fiber_id_Karl = str(rowMain["shotid"]) + "_" + str(row["exp"][4:5]) \
                                + "_" + multiframe + "_" \
                                + str(int(row['multiname'][21:24])).zfill(3)
                karl_weight = row['weight']
                
                rowMain['inputid'] = inputid_i
                
                for col in colnames:
                    try:
                        rowMain[col] = row[col]
                    except:
                        pass

                rowMain['detectname'] = get_detectname(row['ra'], row['dec'])
                        
                selspec = spectable['col11'] == row['src_index']
                
                rowspectra = tableSpectra.row

                rowspectra["detectid"] = detectidx

                dataspec = spectable[selspec]
                
                rowspectra["spec1d"] = dataspec["col2"] / dataspec["col9"]
                rowspectra["spec1d_err"] = dataspec["col3"] / dataspec["col9"]
                rowspectra["wave1d"] = dataspec["col1"]
                rowspectra["spec1d_nc"] = dataspec["col2"]
                rowspectra["spec1d_nc_err"] = dataspec["col3"]
                rowspectra["counts1d"] = dataspec["col4"]
                rowspectra["counts1d_err"] = dataspec["col5"]
                rowspectra["apsum_counts"] = dataspec["col6"]
                rowspectra["apsum_counts_err"] = dataspec["col7"]
                rowspectra["apcor"] = dataspec["col9"]
                rowspectra["flag_pix"] = dataspec["col10"]

                #rowspectra.append()
                

                # add fiber info for each detection

                filefiberinfo = op.join(args.detect_path, amp_i + ".list")
                fibertable = Table.read(filefiberinfo, format="ascii.no_header")

                selfiber = fibertable['col16'] == row['src_index']

                datafiber = fibertable[selfiber]

                # check to see if any of the 5 highest weight fibers fall on a bad amplifier

                mf_array = []
                weight_array =[]
                for ifiber in np.arange(np.size(datafiber)):
                    multiname = datafiber["col5"][ifiber]

                    mf_array.append( multiname[0:20])
                    weight_array.append( datafiber["col14"][ifiber])

                isort = np.flipud(np.argsort(weight_array) )

                sort_mf = np.array(mf_array)[isort]
                
                for multiframe in sort_mf[0:5]:
                    
                    if args.date and args.observation:
                        ampflag = amp_stats['flag'][amp_stats['multiframe'] == multiframe][0]
                        
                    elif args.month:
                        selamp = (amp_stats['shotid'] == rowMain['shotid']) * (amp_stats['multiframe'] == multiframe)
                        ampflag = amp_stats['flag'][selamp]
                    
                    if np.size(ampflag) == 0:
                        args.log.error('No ampflag for '
                                       + str(rowMain['shotid'])
                                       + ' ' + multiframe)
                        
                    if ampflag==False:
                        break

                # skip appending source to Fibers and Spectra table
                if ampflag == False:
                    continue
                
                for ifiber in np.arange(np.size(datafiber)):
                    rowfiber = tableFibers.row
                    rowfiber["detectid"] = detectidx
                    rowfiber["ra"] = datafiber["col1"][ifiber]
                    rowfiber["dec"] = datafiber["col2"][ifiber]
                    rowfiber["x_ifu"] = datafiber["col3"][ifiber]
                    rowfiber["y_ifu"] = datafiber["col4"][ifiber]
                    rowfiber["expnum"] = int(str(datafiber["col6"][ifiber])[3:5])
                    multiname = datafiber["col5"][ifiber]
                    multiframe = multiname[0:20]
                    fiber_id_i = (
                        str(rowMain["shotid"])
                        + "_"
                        + str(int(rowfiber["expnum"]))
                        + "_"
                        + multiframe
                        + "_"
                        + str(int(multiname[21:24])).zfill(3)
                    )
                    rowfiber["fiber_id"] = fiber_id_i
                    rowfiber["multiframe"] = multiframe
                    rowfiber["specid"] = multiframe[6:9]
                    rowfiber["ifuslot"] = multiframe[10:13]
                    rowfiber["ifuid"] = multiframe[14:17]
                    rowfiber["amp"] = multiframe[18:20]
                    rowfiber["fibnum"] = int(multiname[21:24])
                    rowfiber["distance"] = datafiber["col7"][ifiber]
                    rowfiber["wavein"] = datafiber["col8"][ifiber]
                    rowfiber["timestamp"] = datafiber["col9"][ifiber]
                    rowfiber["date"] = datafiber["col10"][ifiber]
                    rowfiber["obsid"] = str(datafiber["col11"][ifiber])[0:3]
                    rowfiber["x_raw"] = datafiber["col12"][ifiber]
                    rowfiber["y_raw"] = datafiber["col13"][ifiber]
                    rowfiber["flag"] = datafiber["col15"][ifiber]
                    rowfiber["weight"] = datafiber["col14"][ifiber]

                    rowfiber.append()
                
                # Now append brightest fiber info to Detections table:
                ifiber = np.argmax(datafiber["col14"])
                multiname = datafiber["col5"][ifiber]
                multiframe = multiname[0:20]
                rowMain["expnum"] = int(str(datafiber["col6"][ifiber])[3:5])
                fiber_id_i = (
                    str(rowMain["shotid"])
                    + "_"
                    + str(rowMain["expnum"])
                    + "_"
                    + multiframe
                    + "_"
                    + str(int(multiname[21:24])).zfill(3)
                )

                if fiber_id_i == fiber_id_Karl:
                    pass
                else:
                    weight = datafiber["col14"][ifiber]
                    weightdif = np.abs(weight-karl_weight)
                    if (weightdif > 0.001):
                        args.log.error("Karl's FiberID does not match: " + inputid_i)
                    
                rowMain["fiber_id"] = fiber_id_i
                rowMain["multiframe"] = multiframe
                rowMain["specid"] = multiframe[6:9]
                rowMain["ifuslot"] = multiframe[10:13]
                rowMain["ifuid"] = multiframe[14:17]
                rowMain["amp"] = multiframe[18:20]
                rowMain["fibnum"] = int(multiname[21:24])
                rowMain["x_raw"] = datafiber["col12"][ifiber]
                rowMain["y_raw"] = datafiber["col13"][ifiber]
                rowMain["x_ifu"] = datafiber["col3"][ifiber]
                rowMain["y_ifu"] = datafiber["col4"][ifiber]
                rowMain["weight"] = datafiber["col14"][ifiber]

                rowMain.append()
                rowspectra.append()

                detectidx += 1
                
            
        tableMain.flush()
        tableSpectra.flush()
        tableFibers.flush()

        ifu_stat_tab = Table([amplist, ndet, ndet_sel], names=['ampid', 'ndet','ndetsel'])

        if args.month:
            ifutabname = 'ifustat_' + str(args.month) + '.tab'
        else:
            ifutabname = 'ifustat_'+ str(args.date) + str(args.observation).zfill(3) + '.tab'

                                    
        ifu_stat_tab.write(ifutabname, format='ascii', overwrite=True)
    
    # create completely sorted index on the detectid
    # to make queries against that column much faster
    if args.append:
        args.log.info("Reindexing the detectid column")
        tableMain.cols.detectid.reindex()
        tableFibers.cols.detectid.reindex()
        tableSpectra.cols.detectid.reindex()
        tableFibers.flush()  # just to be safe
        tableSpectra.flush()
        tableMain.flush()
    else:
        tableMain.cols.detectid.create_csindex()
        tableFibers.cols.detectid.create_csindex()
        tableSpectra.cols.detectid.create_csindex()
        tableFibers.flush()  # just to be safe
        tableSpectra.flush()
        tableMain.flush()
    args.log.info("File finished: %s" % outfilename)
    fileh.close()


if __name__ == "__main__":
    main()
