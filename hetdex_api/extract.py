#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Mon Mar 11 11:48:55 2019

@author: gregz
"""

import numpy as np

from astropy.convolution import Gaussian2DKernel, convolve
from astropy.coordinates import SkyCoord
from astropy.modeling.models import Moffat2D, Gaussian2D
from astropy import units as u
from scipy.interpolate import griddata, LinearNDInterpolator
from shot import Fibers
import imp

input_utils = imp.load_source('input_utils',
                              '/work/03946/hetdex/hdr1/software/HETDEX_API/'
                              'input_utils.py')

class Extract:
    def __init__(self, wave=None):
        '''
        Initialize Extract class
        
        Parameters
        ----------
        wave: numpy 1d array
            wavelength of calfib extension for hdf5 files, does not need to be
            set unless needed by development team
        '''
        if wave is not None:
            self.wave = wave
        else:
            self.wave = self.get_wave()
        self.get_ADR()
        self.log = input_utils.setup_logging('Extract')
    
    def set_dither_pattern(self, dither_pattern=None):
        ''' 
        Set dither pattern (default if None given)
        
        Parameters
        ----------
        dither_pattern: numpy array (length of exposures)
            only necessary if the dither pattern isn't the default
        '''
        if dither_pattern is None:
            self.dither_pattern = np.array([[0., 0.], [1.27, -0.73],
                                            [1.27, 0.73]])
        else:
            self.dither_pattern = dither_pattern

    def get_wave(self):
        ''' Return implicit wavelength solution for calfib extension '''
        return np.linspace(3470, 5540, 1036)

    def get_ADR(self, angle=0.):
        ''' 
        Use default ADR from Karl Gebhardt (adjusted by Greg Zeimann)

        Parameters
        ----------
        angle: float
            angle=0 along x-direction, appropriate if observing at PA
        dither_pattern: numpy array (length of exposures)
            only necessary if the dither pattern isn't the default
        '''
        wADR = [3500., 4000., 4500., 5000., 5500.]
        ADR = [-0.74, -0.4, -0.08, 0.08, 0.20]
        ADR = np.polyval(np.polyfit(wADR, ADR, 3), self.wave)
        self.ADRx = np.cos(np.deg2rad(angle)) * ADR
        self.ADRy = np.sin(np.deg2rad(angle)) * ADR

    def load_shot(self, shot_input, dither_pattern=None):
        '''
        Load fiber info from hdf5 for given shot_input
        
        Parameters
        ----------
        shot_input: str
            e.g., 20190208v024 or 20190208024
        '''
        self.shot = shot_input
        self.fibers = Fibers(self.shot)
        self.set_dither_pattern(dither_pattern=dither_pattern)

        
    def convert_radec_to_ifux_ifuy(self, ifux, ifuy, ra, dec, rac, decc):
        '''
        Input SkyCoord object for sources to extract
        
        Parameters
        ----------
        coord: SkyCoord object
            single ra and dec to turn into ifux and ifuy coordinates
        '''
        if len(ifuy) < 2:
            return None, None
        ifu_vect = np.array([ifuy[1] - ifuy[0], ifux[1] - ifux[0]])
        radec_vect = np.array([(ra[1] - ra[0]) * np.cos(np.deg2rad(dec[0])),
                              dec[1] - dec[0]])
        V = np.sqrt(ifu_vect[0]**2 + ifu_vect[1]**2)
        W = np.sqrt(radec_vect[0]**2 + radec_vect[1]**2)
        scale_vect = np.array([3600., 3600.])
        v = ifu_vect * np.array([1., 1.])
        w = radec_vect * scale_vect
        W =  np.sqrt(np.sum(w**2))
        ang1 = np.arctan2(v[1] / V, v[0] / V)
        ang2 = np.arctan2(w[1] / W, w[0] / W)
        ang1 += (ang1 < 0.) * 2. * np.pi
        ang2 += (ang2 < 0.) * 2. * np.pi
        theta = ang1 - ang2
        dra = (rac - ra[0]) * np.cos(np.deg2rad(dec[0])) * 3600.
        ddec = (decc - dec[0]) * 3600.
        dx = np.cos(theta) * dra - np.sin(theta) * ddec
        dy = np.sin(theta) * dra + np.cos(theta) * ddec
        yc = dx + ifuy[0]
        xc = dy + ifux[0]
        return xc, yc

    def get_fiberinfo_for_coord(self, coord, radius=8.):
        ''' 
        Grab fibers within a radius and get relevant info
        
        Parameters
        ----------
        coord: SkyCoord Object
            a single SkyCoord object for a given ra and dec
        
        Returns
        -------
        ifux: numpy array (length of number of fibers)
            ifu x-coordinate accounting for dither_pattern
        ifuy: numpy array (length of number of fibers)
            ifu y-coordinate accounting for dither_pattern
        ra: numpy array (length of number of fibers)
            Right ascension of fibers
        dec: numpy array (length of number of fibers)
            Declination of fibers
        spec: numpy 2d array (number of fibers by wavelength dimension)
            Calibrated spectra for each fiber
        spece: numpy 2d array (number of fibers by wavelength dimension)
            Error for calibrated spectra
        mask: numpy 2d array (number of fibers by wavelength dimension)
            Mask of good values for each fiber and wavelength
        '''
        idx = self.fibers.query_region_idx(coord, radius=radius/3600.)
        fiber_lower_limit = 5
        if len(idx) < fiber_lower_limit:
            self.log.warning('Not enough fibers found within radius to do'
                             ' an extraction')
            return None
        ifux = self.fibers.table.read_coordinates(idx, 'ifux')
        ifuy = self.fibers.table.read_coordinates(idx, 'ifuy')
        ra = self.fibers.table.read_coordinates(idx, 'ra')
        dec = self.fibers.table.read_coordinates(idx, 'dec')
        spec = self.fibers.table.read_coordinates(idx, 'calfib')
        spece = self.fibers.table.read_coordinates(idx, 'calfibe')
        ftf = self.fibers.table.read_coordinates(idx, 'fiber_to_fiber')
        mask = self.fibers.table.read_coordinates(idx, 'Amp2Amp')
        mask = (mask > 1e-8) * (np.median(ftf, axis=1) > 0.5)[:, np.newaxis]
        expn = np.array(self.fibers.table.read_coordinates(idx, 'expnum'),
                        dtype=int)
        ifux[:] = ifux + self.dither_pattern[expn-1, 0]
        ifuy[:] = ifuy + self.dither_pattern[expn-1, 1]
        xc, yc = self.convert_radec_to_ifux_ifuy(ifux, ifuy, ra, dec,
                                                 coord.ra.deg, coord.dec.deg)
        return ifux, ifuy, xc, yc, ra, dec, spec, spece, mask

    def get_starcatalog_params(self):
        '''
        Load Star Catalog coordinates, g' magnitude, and star ID
        
        Returns
        -------
        coords: SkyCoord Object
            SkyCoord object of the ra and dec's of the stars
        gmag: numpy array (float)
            g' magnitude of the stars in the star catalog
        starid: numpy array (int)
            Object ID from the original catalog of the stars (e.g., SDSS)
        '''
        if not hasattr(self, 'fibers'):
            self.log.warning('Please do load_shot to get star catalog params.')
            return None
        ras = self.fibers.hdfile.root.Astrometry.StarCatalog.cols.ra_cat[:]
        decs = self.fibers.hdfile.root.Astrometry.StarCatalog.cols.dec_cat[:]
        gmag = self.fibers.hdfile.root.Astrometry.StarCatalog.cols.g[:]
        starid = self.fibers.hdfile.root.Astrometry.StarCatalog.cols.star_ID[:]

        coords = SkyCoord(ras*u.deg, decs*u.deg, frame='fk5')
        return coords, gmag, starid

    def intersection_area(self, d, R, r):
        """
        Return the area of intersection of two circles.
        The circles have radii R and r, and their centers are separated by d.
    
        Parameters
        ----------
        d : float
            separation of the two circles
        R : float
            Radius of the first circle
        r : float
            Radius of the second circle
        """
    
        if d <= abs(R-r):
            # One circle is entirely enclosed in the other.
            return np.pi * min(R, r)**2
        if d >= r + R:
            # The circles don't overlap at all.
            return 0
    
        r2, R2, d2 = r**2, R**2, d**2
        alpha = np.arccos((d2 + r2 - R2) / (2*d*r))
        beta = np.arccos((d2 + R2 - r2) / (2*d*R))
        answer = (r2 * alpha + R2 * beta -
                  0.5 * (r2 * np.sin(2*alpha) + R2 * np.sin(2*beta)))
        return answer

    def tophat_psf(self, radius, boxsize, scale, fibradius=0.75):
        '''
        Tophat PSF profile image 
        (taking fiber overlap with fixed radius into account)
        
        Parameters
        ----------
        radius: float
            Radius of the tophat PSF
        boxsize: float
            Size of image on a side for Moffat profile
        scale: float
            Pixel scale for image
        
        Returns
        -------
        zarray: numpy 3d array
            An array with length 3 for the first axis: PSF image, xgrid, ygrid
        '''
        xl, xh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        yl, yh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        x, y = (np.arange(xl, xh, scale), np.arange(yl, yh, scale))
        xgrid, ygrid = np.meshgrid(x, y)
        t = np.linspace(0., np.pi * 2., 360)
        r = np.arange(radius - fibradius, radius + fibradius * 7./6.,
                      1. / 6. * fibradius)
        xr, yr, zr = ([], [], [])
        for i, ri in enumerate(r):
            xr.append(np.cos(t) * ri)
            yr.append(np.sin(t) * ri)
            zr.append(self.intersection_area(ri, radius, fibradius) *
                      np.ones(t.shape) / (np.pi * fibradius**2))
        xr, yr, zr = [np.hstack(var) for var in [xr, yr, zr]]
        psf = griddata(np.array([xr, yr]).swapaxes(0,1), zr, (xgrid, ygrid),
                       method='linear')
        psf[np.isnan(psf)]=0.
        zarray = np.array([psf, xgrid, ygrid])
        zarray[0] /= zarray[0].sum()
        return zarray

    def gaussian_psf(self, xstd, ystd, theta, boxsize, scale):
        '''
        Gaussian PSF profile image 
        
        Parameters
        ----------
        xstd: float
            Standard deviation of the Gaussian in x before rotating by theta
        ystd: float
            Standard deviation of the Gaussian in y before rotating by theta
        theta: float
            Rotation angle in radians.
            The rotation angle increases counterclockwise
        boxsize: float
            Size of image on a side for Moffat profile
        scale: float
            Pixel scale for image
        
        Returns
        -------
        zarray: numpy 3d array
            An array with length 3 for the first axis: PSF image, xgrid, ygrid
        '''
        M = Gaussian2D()
        M.x_stddev.value = xstd
        M.y_stddev.value = ystd
        M.theta.value = theta
        xl, xh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        yl, yh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        x, y = (np.arange(xl, xh, scale), np.arange(yl, yh, scale))
        xgrid, ygrid = np.meshgrid(x, y)
        zarray = np.array([M(xgrid, ygrid), xgrid, ygrid])
        zarray[0] /= zarray[0].sum()
        return zarray

    def moffat_psf(self, seeing, boxsize, scale, alpha=3.5):
        '''
        Moffat PSF profile image
        
        Parameters
        ----------
        seeing: float
            FWHM of the Moffat profile
        boxsize: float
            Size of image on a side for Moffat profile
        scale: float
            Pixel scale for image
        alpha: float
            Power index in Moffat profile function
        
        Returns
        -------
        zarray: numpy 3d array
            An array with length 3 for the first axis: PSF image, xgrid, ygrid
        '''
        M = Moffat2D()
        M.alpha.value = alpha
        M.gamma.value = 0.5 * seeing / np.sqrt(2**(1./ M.alpha.value) - 1.)
        xl, xh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        yl, yh = (0. - boxsize / 2., 0. + boxsize / 2. + scale)
        x, y = (np.arange(xl, xh, scale), np.arange(yl, yh, scale))
        xgrid, ygrid = np.meshgrid(x, y)
        zarray = np.array([M(xgrid, ygrid), xgrid, ygrid])
        zarray[0] /= zarray[0].sum()
        return zarray

    def model_psf(self, gmag_limit=21., radius=8., pixscale=0.25,
                  boundary=[-21., 21., -21., 21.]):
        '''
        Model the VIRUS on-sky PSF for a set of three exposures
        
        Parameters
        ----------
        gmag_limit: float
            Only stars brighter than this value will be used to model the psf
        radius: float
            Radius in arcseconds used to collect fibers around a given coord
        pixscale: float
            Pixel scale in arcseconds of the psf image
        boundary: list of 4 values
            [x_lower, x_higher, y_lower, y_higher] limits for including a star
            in ifu coordinates
        
        Returns
        -------
        zarray: numpy 3d array
            An array with length 3 for the first axis: PSF image, xgrid, ygrid
        '''
        # Fit a box in a circle (0.95 factor for caution)
        boxsize = int(np.sqrt(2.) * radius * 0.95 / pixscale) * pixscale

        coords, gmag, starid = self.get_starcatalog_params()

        psf_list = []
        for i, coord in enumerate(coords):
            # Only use stars that are bright enough and not near the edge
            if gmag[i] > gmag_limit:
                self.log.info('PSF model StarID: %i too faint: %0.2f' %
                              (starid[i], gmag[i]))
                continue
            result = self.get_fiberinfo_for_coord(coord, radius=radius)
            if result is None:
                continue
            ifux, ifuy, xc, yc, ra, dec, data, datae, mask = result
            in_bounds = ((xc > boundary[0]) * (xc < boundary[1]) *
                         (yc > boundary[2]) * (yc < boundary[3]))
            if not in_bounds:
                self.log.info('PSF model StarID: %i on edge: %0.2f, %0.2f' %
                              (starid[i], xc, yc))
                continue
            psfi = self.make_collapsed_image(xc, yc, ifux, ifuy, data, mask,
                                             boxsize=boxsize, scale=pixscale)
            psf_list.append(psfi)
        
        if len(psf_list) == 0:
            self.log.warning('No suitable stars for PSF')
            self.log.warning('Using default moffat PSF with 1.8" seeing')
            return self.moffat_psf(1.8, boxsize, pixscale)
        
        self.log.info('%i suitable stars for PSF' % len(psf_list))
        try:
            C = np.array(psf_list)
        except:
            self.log.warning('WTF!!')
        A = [psfi[0] for psfi in psf_list]
        avg_psf_image = np.nanmedian(A, axis=0)
        avg_psf_image[np.isnan(avg_psf_image)] = 0.0
        zarray = np.array([avg_psf_image, C[0, 1], C[0, 2]])
        return zarray
    
    def make_collapsed_image(self, xc, yc, xloc, yloc, data, mask,
                             scale=0.25, seeing_fac=1.8, boxsize=4.,
                             wrange=[3470, 5540], nchunks=11,
                             convolve_image=False):
        ''' 
        Collapse spectra to make a signle image on a rectified grid.  This
        may be done for a wavelength range and using a number of chunks
        of wavelength to take ADR into account.
        
        Parameters
        ----------
        xc: float
            The ifu x-coordinate for the center of the collapse frame
        yc: float 
            The ifu y-coordinate for the center of the collapse frame
        xloc: numpy array
            The ifu x-coordinate for each fiber
        yloc: numpy array
            The ifu y-coordinate for each fiber
        data: numpy 2d array
            The calibrated spectra for each fiber
        mask: numpy 2d array
            The good fiber wavelengths to be used in collapsed frame
        scale: float
            Pixel scale for output collapsed image
        seeing_fac: float
            seeing_fac = 2.35 * radius of the Gaussian kernel used 
            if convolving the images to smooth out features. Unit: arcseconds
        boxsize: float
            Length of the side in arcseconds for the convolved image
        wrange: list
            The wavelength range to use for collapsing the frame
        nchunks: int
            Number of chunks used to take ADR into account when collapsing
            the fibers.  Use a larger number for a larger wavelength.
            A small wavelength may only need one chunk
        convolve_image: bool
            If true, the collapsed frame is smoothed at the seeing_fac scale
        
        Returns
        -------
        zarray: numpy 3d array
            An array with length 3 for the first axis: PSF image, xgrid, ygrid
        '''
        a, b = data.shape
        xl, xh = (xc - boxsize / 2., xc + boxsize / 2. + scale)
        yl, yh = (yc - boxsize / 2., yc + boxsize / 2. + scale)
        x, y = (np.arange(xl, xh, scale), np.arange(yl, yh, scale))
        xgrid, ygrid = np.meshgrid(x, y)
        S = np.zeros((a, 2))
        area = np.pi * 0.75**2
        sel = (self.wave > wrange[0]) * (self.wave <= wrange[1])
        I = np.arange(b)
        ichunk = [np.mean(xi) for xi in np.array_split(I[sel], nchunks)]
        ichunk = np.array(ichunk, dtype=int)
        cnt = 0
        image_list = []
        if convolve_image:
            seeing = seeing_fac / scale
            G = Gaussian2DKernel(seeing / 2.35)

        for chunk, mchunk in zip(np.array_split(data[:, sel], nchunks, axis=1),
                                np.array_split(mask[:, sel], nchunks, axis=1)):
            marray = np.ma.array(chunk, mask=mchunk<1e-8)
            image = np.ma.median(marray, axis=1)
            image = image / np.ma.sum(image)
            S[:, 0] = xloc - self.ADRx[ichunk[cnt]]
            S[:, 1] = yloc - self.ADRy[ichunk[cnt]]
            cnt += 1
            grid_z = (griddata(S[~image.mask], image.data[~image.mask],
                               (xgrid, ygrid), method='cubic') *
                      scale**2 / area)
            if convolve_image:
                grid_z = convolve(grid_z, G)
            image_list.append(grid_z)
        image = np.median(image_list, axis=0)
        zarray = np.array([image, xgrid-xc, ygrid-yc])
        return zarray

    def get_psf_curve_of_growth(self, psf):
        '''
        Analyse the curve of growth for an input psf
        
        Parameters
        ----------
        psf: numpy 3d array
            zeroth dimension: psf image, xgrid, ygrid
        
        Returns
        -------
        r: numpy array
            radius in arcseconds
        cog: numpy array
            curve of growth for psf
        '''
        r = np.sqrt(psf[1]**2 + psf[2]**2).ravel()
        inds = np.argsort(r)
        maxr = psf[1].max()
        sel = r[inds] <= maxr
        cog = (np.cumsum(psf[0].ravel()[inds][sel]) /
               np.sum(psf[0].ravel()[inds][sel]))
        return r[inds][sel], cog
    
    def build_weights(self, xc, yc, ifux, ifuy, psf):
        '''
        Build weight matrix for spectral extraction
        
        Parameters
        ----------
        xc: float
            The ifu x-coordinate for the center of the collapse frame
        yc: float 
            The ifu y-coordinate for the center of the collapse frame
        xloc: numpy array
            The ifu x-coordinate for each fiber
        yloc: numpy array
            The ifu y-coordinate for each fiber
        psf: numpy 3d array
            zeroth dimension: psf image, xgrid, ygrid
        
        Returns
        -------
        weights: numpy 2d array (len of fibers by wavelength dimension)
            Weights for each fiber as function of wavelength for extraction
        '''
        S = np.zeros((len(ifux), 2))
        T = np.array([psf[1].ravel(), psf[2].ravel()]).swapaxes(0, 1)
        I = LinearNDInterpolator(T, psf[0].ravel(),
                                 fill_value=0.0)
        weights = np.zeros((len(ifux), len(self.wave)))
        scale = np.abs(psf[1][0, 1] - psf[1][0, 0])
        area = 0.75**2 * np.pi
        for i in np.arange(len(self.wave)):
            S[:, 0] = ifux - self.ADRx[i] - xc
            S[:, 1] = ifuy - self.ADRy[i] - yc
            weights[:, i] = I(S[:, 0], S[:, 1]) * area / scale**2

        return weights

    def get_spectrum(self, data, error, mask, weights):
        '''
        Weighted spectral extraction
        
        Parameters
        ----------
        data: numpy 2d array (number of fibers by wavelength dimension)
            Flux calibrated spectra for fibers within a given radius of the 
            source.  The radius is defined in get_fiberinfo_for_coord().
        error: numpy 2d array
            Error of the flux calibrated spectra 
        mask: numpy 2d array (bool)
            Mask of good wavelength regions for each fiber
        weights: numpy 2d array (float)
            Normalized extraction model for each fiber
        
        Returns
        -------
        spectrum: numpy 1d array
            Flux calibrated extracted spectrum
        spectrum_error: numpy 1d array
            Error for the flux calibrated extracted spectrum
        '''
        spectrum = (np.sum(data * mask * weights, axis=0) /
                    np.sum(mask * weights**2, axis=0))
        spectrum_error = (np.sqrt(np.sum(error**2 * mask * weights, axis=0)) /
                          np.sum(mask * weights**2, axis=0))
        # Only use wavelengths with enough weight to avoid large noise spikes
        w = np.sum(mask * weights**2, axis=0)
        sel = w < np.median(w)*0.1
        spectrum[sel] = np.nan
        spectrum_error[sel] = np.nan
        
        return spectrum, spectrum_error
