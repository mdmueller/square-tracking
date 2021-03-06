#!/usr/bin/env python

from __future__ import division

from operator import itemgetter

from math import sqrt
from cmath import phase, polar
import numpy as np
from numpy.linalg import norm
from scipy.spatial.distance import pdist, cdist
from scipy.spatial import Voronoi, cKDTree, Delaunay
from scipy.ndimage import gaussian_filter
from scipy.signal import hilbert
from scipy.fftpack import fft2
from scipy.stats import rv_continuous, vonmises
from scipy.optimize import curve_fit
from skimage.morphology import disk, binary_dilation

if __name__=='__main__':
    from socket import gethostname
    hostname = gethostname()
    if 'foppl' in hostname:
        locdir = '/home/lawalsh/Granular/Squares/spatial_diffusion/'
    elif 'rock' in hostname:
        computer = 'rock'
        import matplotlib.pyplot as pl
        import matplotlib.cm as cm
        locdir = '/Users/leewalsh/Physics/Squares/spatial_diffusion/'
    else:
        print "computer not defined\nwhere are you working?"

ss = 92   # side length of square in pixels
rr = 1255 # radius of disk in pixels
x0, y0 = 1375, 2020 # center of disk within image, in pixels

pi = np.pi
tau = 2*pi

def pair_indices(n):
    """ pairs of indices to a 1d array of objects.
        equivalent to but faster than `np.triu_indices(n, 1)`
        from: http://stackoverflow.com/questions/22390418/pairwise-displacement-vectors-among-set-of-points/

        To index the upper triangle of a matrix, just use the returned tuple.
        Otherwise, use `i` and `j` separately to index the first then second of
        the pair
    """
    rng = np.arange(1, n)
    i = np.repeat(rng - 1, rng[::-1])
    j = np.arange(n*(n-1)//2) + np.repeat(n - np.cumsum(rng[::-1]), rng[::-1])
    return i, j

def radial_distribution(positions, dr=ss/5, dmax=None, rmax=None, nbins=None, margin=0, do_err=False):
    """ radial_distribution(positions):
        the pair correlation function g(r)
        calculated using a histogram of distances between particle pairs
        excludes pairs in margin of given width
    """
    center = 0.5*(positions.max(0) + positions.min(0))
    d = np.hypot(*(positions - center).T)
    r = cdist(positions, positions) # faster than squareform(pdist(positions)) wtf
    radius = np.maximum(r.max()/2, d.max())#TODO accuracy is critical.. add ss/2?
    if rmax is None:
        rmax = 2*radius # this will have terrible statistics at large r
    if nbins is None:
        nbins = rmax/dr
    if dmax is None:
        dmax = radius - margin
    ind = pair_indices(len(positions))
    # for weighting, use areas of the annulus, which is:
    #   number * arclength * dr = N alpha r dr
    #   where alpha = 2 arccos( (r2 + d2 - R2) / 2 r d )
    cosalpha = 0.5 * (r*r + d*d - radius*radius) / (r * d)
    alpha = 2 * np.arccos(np.clip(cosalpha, -1, None))
    dmask = d <= dmax
    w = np.where(dmask, np.reciprocal(alpha*r*dr), 0)
    w = 0.5*(w + w.T)
    assert np.all(np.isfinite(w[ind]))
    n = np.count_nonzero(dmask) # number of 'bulk' (inner) particles
    #n = 0.5*(1 + sqrt(1 + 8*np.count_nonzero(w[ind]))) # effective N from no. of pairs
    #n = len(w) # total number of particles
    w *= 2/n
    assert np.allclose(positions.shape[0], [len(r), len(d), len(w), len(positions)])
    ret = np.histogram(r[ind], bins=nbins, range=(0, rmax), weights=w[ind])
    if do_err:
        return ret, np.histogram(r[ind], bins=nbins, range=(0, rmax)), n
    else:
        return ret + (n,)

def rectify(positions, margin=0, dangonly=False):
    angles, nmask, dmask = pair_angles(positions, margin=margin)
    try:
        # find four modal angles and gaps
        # rotate by angle of greater of first two gaps
        # so that first gap is larger of two, last gap is smaller
        pang = primary_angles(angles, m=4, bins=720, ret_hist=False)[0]
        dang = dtheta(pang, np.roll(pang, -1), m=1) # dang[i] = pang[i] - pang[i-1]
        rectang = np.nan if dangonly else -pang[np.argmax(dang[:2])]
    except RuntimeError:
        print "Can't find four peaks, using one"
        rectang = np.nan if dangonly else -pair_angle_op(angles, nmask, m=4)[1]
        dang = np.array([np.nan, np.nan, np.nan, np.nan])
    return rectang, dang

def distribution(positions, rmax=10, bins=10, margin=0, rectang=0):
    if margin < ss: margin *= ss
    center = 0.5*(positions.max(0) + positions.min(0))
    d = np.hypot(*(positions - center).T)
    dmask = d < d.max() - margin
    r = cdist(positions, positions[dmask])#.ravel()
    radius = np.maximum(r.max()/2, d.max())
    cosalpha = 0.5 * (r**2 + d[dmask]**2 - radius**2) / (r * d[dmask])
    alpha = 2 * np.arccos(np.clip(cosalpha, -1, None))
    dr = radius / bins
    w = dr**-2 * tau/alpha
    w[~np.isfinite(w)] = 0
    if rmax < ss: rmax *= ss
    rmask = r < rmax
    displacements = positions[:, None] - positions[None, dmask] #origin must be within margin
    if rectang:
        if rectang is True:
            rectang = rectify(positions, margin=margin)[0]
        rotate2d(displacements, rectify(positions, margin=margin))
    return np.histogramdd(displacements[rmask], bins=bins, weights=w[rmask])[0]

def rotate2d(vectors, angles):
    """ rotate vectors by angles
        *** beware *** modifies vectors in place ***

        vectors must have shape (..., 2)
        angles broadcast to shape (...)
    """
    assert vectors.shape[-1] == 2, "must be two dimensional vectors"
    c, s = np.cos(angles), np.sin(angles)
    x, y = vectors[..., 0], vectors[..., 1]
    x[:], y[:] = x*c - y*s, y*c + x*s
    return

def get_positions(data, frame, pid=None):
    """ get_positions(data,frame)
        
        Takes:
            data: structured array of data
            frame: int or list of ints of frame number

        Returns:
            list of tuples (x,y) of positions of all particles in those frames
    """
    fmask = np.in1d(data['f'], frame) if np.iterable(frame) else data['f']==frame
    if pid is not None:
        fiddata = data[fmask & (data['id']==pid)]
        return np.array(fiddata['x'], fiddata['y'])
    return np.column_stack((data['x'][fmask], data['y'][fmask]))

def avg_hists(gs, rgs):
    """ avg_hists(gs,rgs)
        takes:
            gs: an array of g(r) for several frames
            rgs: their associated r values
        returns:
            g_avg: the average of gs over frames
            dg_avg: their std dev / sqrt(length)
            rg: r for the avgs (just uses rgs[0] for now) 
    """
    assert np.all([np.allclose(rgs[i], rgs[j])
        for i in xrange(len(rgs)) for j in xrange(len(rgs))])
    rg = rgs[0]
    g_avg = gs.mean(0)
    dg_avg = gs.std(0)/sqrt(len(gs))
    return g_avg, dg_avg, rg

def build_gs(data, framestep=1, dr=None, dmax=None, rmax=None, margin=0, do_err=False):
    """ build_gs(data, framestep=10)
        calculates and builds g(r) for each (framestep) frames
        Takes:
            data: the structued array of data
            framestep=10: how many frames to skip
        Returns:
            gs: an array of g(r) for several frames
            rgs: their associated r values
    """
    frames = np.arange(data['f'].min(), data['f'].max()+1, framestep)
    dr = ss*(.1 if dr is None else dr)
    #if rmax is None:
        #rmax = rr - ss*3
    #elif rmax:
        #rmax = rr - ss*rmax
    nbins = rmax/dr if rmax and dr else None
    gs = rgs = egs = ergs = None
    for nf, frame in enumerate(frames):
        positions = get_positions(data, frame)
        g, rg, n = radial_distribution(positions, dr=dr, dmax=dmax, rmax=rmax, nbins=nbins,
                               margin=margin, do_err=do_err)
        if do_err:
            (g, rg), (eg, erg), n = g, rg, n
            erg = erg[1:]
        rg = rg[1:]
        if gs is None:
            nbins = g.size
            gs = np.zeros((frames.size, nbins))
            rgs = gs.copy()
            if do_err:
                egs = np.zeros((frames.size, nbins))
                ergs = gs.copy()
        gs[nf,:len(g)]  = g
        rgs[nf,:len(g)] = rg
        if do_err:
            egs[nf, :len(eg)] = eg
            ergs[nf, :len(eg)] = erg
    return ((gs, rgs), (egs, ergs), n) if do_err else (gs, rgs, n)

def structure_factor(positions, m=4, margin=0):
    """return the 2d structure factor"""
    #center = 0.5*(positions.max(0) + positions.min(0))
    inds = np.round(positions - positions.min()).astype(int)
    f = np.zeros(inds.max(0)+1)
    f[inds[:,0], inds[:,1]] = 1
    f = binary_dilation(f, disk(ss/2))
    return fft2(f, overwrite_x=True)

def orient_op(orientations, positions, m=4, margin=0, ret_complex=True, do_err=False):
    """ orient_op(orientations, m=4)
        Returns the global m-fold particle orientational order parameter

                1   N    i m theta
        Phi  = --- SUM e          j
           m    N  j=1
    """
    np.mod(orientations, tau/m, orientations) # what's this for? (was tau/4 not tau/m)
    if margin:
        if margin < ss: margin *= ss
        center = 0.5*(positions.max(0) + positions.min(0))
        d = np.hypot(*(positions - center).T)
        orientations = orientations[d < d.max() - margin]
    phi = np.exp(m*orientations*1j).mean()
    if do_err:
        err = phi.std(ddof=1)/sqrt(phi.size)
        return (phi, err) if ret_complex else (np.abs(phi), err)
    else:
        return phi if ret_complex else np.abs(phi)

def dtheta(i, j=None, m=4, sign=False):
    """ given two angles or one array (N,2) of pairs
        returns the _smallest angle between them, modulo m
        if sign is True, retuns a negative angle for i<j, else abs
    """
    ma = tau/m
    if j is not None:
        diff = i - j
    elif i.shape[1]==2:
        diff = np.subtract(*i.T)
    diff = (diff + ma/2)%ma - ma/2
    return diff if sign else np.abs(diff)

def correlate(r, f, bins=10):
    n, bins = np.histogram(r, bins)
    return np.histogram(r, bins, weights=f)[0]/n, bins

def orient_corr(positions, orientations, m=4, margin=0):
    """ orient_corr():
        the orientational correlation function g_m(r)
        given by mean(phi(0)*phi(r))
    """
    center = 0.5*(positions.max(0) + positions.min(0))
    d = np.hypot(*(positions - center).T)
    if margin < ss: margin *= ss
    loc_mask = d < d.max() - margin
    r = pdist(positions[loc_mask])
    ind = np.column_stack(pair_indices(np.count_nonzero(loc_mask)))
    pairs = orientations[loc_mask][ind]
    diffs = np.cos(m*dtheta(pairs, m=m))
    return r, diffs

def get_neighbors(tess, p, pm=None, ret_pairs=False):
    """ give neighbors in voronoi tessellation v of point id p
        if already calculated, pm is point mask
    """
    if isinstance(tess, Delaunay):
        indices, indptr = tess.vertex_neighbor_vertices
        if np.iterable(p):
            return [indptr[indices[q]:indices[q+1]] for q in p]
        return indptr[indices[p]:indices[p+1]]
    elif isinstance(tess, Voronoi):
        if np.iterable(p):
            raise ValueError, "cannot find neighbors of multiple points with Voronoi"
        pm = tess.ridge_points == p if pm is None else pm[p]
        pm = np.any(pm, 1)
        pairs = tess.ridge_points[pm]
        return pairs if ret_pairs else pairs[pairs != p]

def binder(positions, orientations, bl, m=4, method='ball', margin=0):
    """ Calculate the binder cumulant for a frame, given positions and orientations.

        bl: the binder length scale, such that
            B(bl) = 1 - .333 * S4 / S2^2
        where SN are <phibl^N> averaged over each block/cluster of size bl in frame.
    """
    if margin:
        if margin < ss:
            margin *= ss
        center = 0.5*(positions.max(0) + positions.min(0))
        d = np.hypot(*(positions - center).T)
        dmask = d < d.max() - margin
        positions = positions[dmask]
        orientations = orientations[dmask]
    if 'neigh' in method or 'ball' in method:
        tree = cKDTree(positions)
        balls = tree.query_ball_tree(tree, bl)
        balls, ball_mask = pad_uneven(balls, 0, True, int)
        ball_orient = orientations[balls]
        ball_orient[~ball_mask] = np.nan
        phis = np.nanmean(np.exp(m*ball_orient*1j), 1)
        phi2 = np.dot(phis, phis) / len(phis)
        phiphi = phis*phis
        phi4 = np.dot(phiphi, phiphi) / len(phiphi)
        return 1 - phi4 / (3*phi2*phi2)
    else:
        raise ValueError, "method {} not implemented".format(method)
    #elif method=='block':
        left, right, bottom, top = (positions[:,0].min(), positions[:,0].max(),
                                    positions[:,1].min(), positions[:,1].max())
        xbins, ybins = np.arange(left, right + bl, bl), np.arange(bottom, top + bl, bl)
        blocks = np.rollaxis(np.indices((xbins.size, ybins.size)), 0, 3)
        block_ind = np.column_stack([
                     np.digitize(positions[:,0], xbins),
                     np.digitize(positions[:,1], ybins)])

def pad_uneven(lst, fill=0, return_mask=False, dtype=None):
    """ take uneven list of lists
        return new 2d array with shorter lists padded with fill value"""
    if dtype is None:
        dtype = np.result_type(fill, lst[0][0])
    shape = len(lst), max(map(len, lst))
    result = np.zeros(shape, dtype) if fill==0 else np.full(shape, fill, dtype)
    if return_mask:
        mask = np.zeros(shape, bool)
    for i, row in enumerate(lst):
        result[i, :len(row)] = row
        if return_mask:
            mask[i, :len(row)] = True
    return (result, mask) if return_mask else result

def get_id(data, position, frames=None, tolerance=10e-5):
    """ take a particle's `position' (x,y)
        optionally limit search to one or more `frames'

        return that particle's id
        THIS FUNCTION IS IMPORTED BY otracks.py AND orientation.py
        """
    if frames is not None:
        if np.iterable(frames):
            data = data[np.in1d(data['f'], frames)]
        else:
            data = data[data['f']==frames]
    xmatch = data[abs(data['x']-position[0])<tolerance]
    return xmatch['id'][abs(xmatch['y']-position[1])<tolerance]

def pair_angles(positions, neighborhood=None, ang_type='absolute', margin=0, dub=2*ss):
    """ do something with the angles a given particle makes with its neighbors

        `ang_type` can be 'relative', 'delta', or 'absolute'
        `neighborhood` may be:
            an integer (probably 4, 6, or 8), giving that many nearest neighbors,
            or None (which gives voronoi)
        `margin` is the width of excluded boundary margin
        `dub` is the distance upper bound (won't use pairs farther apart)
    """
    if neighborhood is None or str(neighborhood).lower() in ['voronoi', 'delauney']:
        #method = 'voronoi'
        tess = Delaunay(positions)
        neighbors = get_neighbors(tess, xrange(tess.npoints))
        neighbors, nmask = pad_uneven(neighbors, 0, True, int)
    elif isinstance(neighborhood, int):
        #method = 'nearest'
        tree = cKDTree(positions)
        # tree.query(P, N) returns query particle and N-1 neighbors
        distances, neighbors = tree.query(positions, 1 + neighborhood,
                                          distance_upper_bound=dub)
        assert np.allclose(distances[:,0], 0), "distance to self not zero"
        distances = distances[:,1:]
        assert np.allclose(neighbors[:,0], np.arange(tree.n)), "first neighbor not self"
        neighbors = neighbors[:,1:]
        nmask = np.isfinite(distances)
        neighbors[~nmask] = np.where(~nmask)[0]
    dx, dy = (positions[neighbors] - positions[:, None, :]).T
    angles = np.arctan2(dy, dx).T % tau
    assert angles.shape == neighbors.shape
    if ang_type == 'relative':
        # subtract off angle to nearest neighbor
        angles -= angles[:, 0, None] # None to keep dims
    elif ang_type == 'delta':
        # sort by angle then take diff
        angles[~nmask] = np.inf
        angles.sort(-1)
        angles -= np.roll(angles, 1, -1)
        nmask = np.all(nmask, 1)
    elif ang_type != 'absolute':
        raise ValueError, "unknown ang_type {}".format(ang_type)
    angles[~nmask] = np.nan
    if margin:
        if margin < ss: margin *= ss
        center = 0.5*(positions.max(0) + positions.min(0))
        d = np.hypot(*(positions - center).T)
        dmask = d < d.max() - margin
        assert np.allclose(len(dmask), map(len, [angles, nmask]))
        angles = angles[dmask]
        nmask = nmask[dmask]
    return (angles % tau, nmask) + ((dmask,) if margin else ())

def pair_angle_op(angles, nmask=None, m=4):
    if nmask is not None:
        angles[~nmask] = np.nan
    psims = np.nanmean(np.exp(m*angles*1j), 1)
    psim = np.nanmean(psims)
    return abs(psim), phase(psim)/m, psims

def pair_angle_corr(positions, psims, rbins=10):
    assert len(positions) == len(psims), "positions does not match psi_m(r)"
    i, j = pair_indices(len(positions))
    psi2 = psims[i].conj() * psims[j]
    return correlate(pdist(positions), psi2, rbins)

class vonmises_m(rv_continuous):
    def __init__(self, m):
        self.shapes = ''
        for i in range(m):
            self.shapes += 'k%d,l%d' % (i,i)
        self.shapes += ',scale'
        rv_continuous.__init__(self, a=-np.inf, b=np.inf, shapes=self.shapes)
        self.numargs = 2*m

    def _pdf(self, x, *lks):
        print 'lks', lks
        locs, kappas= lks[:len(lks)/2], lks[len(lks)/2:]
        print 'x', x
        print 'locs', locs
        print 'kapps', kappas
        #return np.sum([vonmises.pdf(x, l, k) for l, k in zip(locs, kappas)], 0)
        ret = np.zeros_like(x)
        for l, k in zip(locs, kappas):
            ret += vonmises.pdf(x, l, k)
        return ret / len(locs)

class vonmises_4(rv_continuous):
    def __init__(self):
        rv_continuous.__init__(self, a=-np.inf, b=np.inf)

    def _pdf(self, x,
             l1, l2, l3, l4,
             k1, k2, k3, k4,
             a1, a2, a3, a4):
        return a1*vonmises.pdf(x, k1, l1) + \
               a2*vonmises.pdf(x, k2, l2) + \
               a3*vonmises.pdf(x, k3, l3) + \
               a4*vonmises.pdf(x, k4, l4) + c

def vm4_pdf(x,
            l1, l2, l3, l4,
            k1, k2, k3, k4,
            a1, a2, a3, a4, c):
    return a1*vonmises.pdf(x, k1, l1) + \
           a2*vonmises.pdf(x, k2, l2) + \
           a3*vonmises.pdf(x, k3, l3) + \
           a4*vonmises.pdf(x, k4, l4) + c

def primary_angles(angles, m=4, bins=720, ret_hist=False):
    angles = angles[angles!=0].ravel()
    h, t = np.histogram(angles, bins, (0, tau), True)
    t = 0.5*(t[1:] + t[:-1])

    l0 = tuple((np.arange(0, tau, tau/m)+t[h.argmax()]) % tau)
    k0 = (100.,) * m
    a0 = (.02,) * m
    c0 = 1e-3,
    guess = l0 + k0 + a0 + c0
    vm_fit = curve_fit(vm4_pdf, t, h, guess)[0]
    l = vm_fit[:m]
    k = vm_fit[m:2*m]
    a = vm_fit[2*m:3*m]
    c = vm_fit[-1]
    if ret_hist:
        return l, k, a, c, h, t
    return l, k, a, c

def domyneighbors(prefix):
    tracksnpz = np.load(locdir+prefix+"_TRACKS.npz")
    data = tracksnpz['data']
    ndata = add_neighbors(data)
    np.savez(locdir+prefix+'_NEIGHBORS.npz',ndata=ndata)

def get_gdata(locdir,ns):
    return dict([
            ('n'+str(n), np.load(locdir+'n'+str(n)+'_GR.npz'))
            for n in ns])

def find_gpeaks(ns,locdir,binmax=258):
    """ find_gpeaks(ns,locdir,binmax)
        finds peaks and valleys in g(r) curve
        takes:
            ns, list of densities to analyse
            locdir, local directory for data
            binmax, the max bin number, hopefully temporary problem
        returns:
            peaks,  list of [list of peaks and list of valleys]
                    in format given by peakdetect.py
    """
    import peakdetect as pk
    #ns = np.array([8,16,32,64,128,192,256,320,336,352,368,384,400,416,432,448])
    binmax = 258
    gdata = get_gdata(locdir,ns)
    peaks  = {}
    maxima = {}
    minima = {}
    for k in gdata:
        extrema = pk.peakdetect(
                gdata[k]['g'][:binmax]/22.0, gdata[k]['rg'][:binmax]/22.,
                lookahead=2.,delta=.0001)
        peaks[k] = extrema
        maxima[k] = np.asarray(extrema[0])
        minima[k] = np.asarray(extrema[1])
    return peaks

def plot_gpeaks(peaks,gdata,pksonly=False,hhbinmax=258):
    """ plot_gpeaks(peaks,gdata,binmax)
        plots locations and/or heights of peaks and/or valleys in g(r)
        takes:
            peaks,  list of peaks from output of find_gpeaks()
            gdata,  g(r) arrays, loaded from get_gdata()
            binmax, the max bin number, hopefully temporary problem
        side affects:
            creates a figure and plots things
        returns:
            nothing
    """
    if computer is 'foppl':
        print "cant do this on foppl"
        return
    pl.figure()
    for k in peaks:
        try:
            pl.plot(gdata[k]['rg'][:binmax]/22.,gdata[k]['g'][:binmax]/22.,',-',label=k)
            #pl.scatter(*np.asarray(peaks[k][0]).T,
            #        marker='o', label=k, c = cm.jet((int(k[1:])-200)*255/300))
            #pl.scatter(*np.asarray(peaks[k][1]).T,marker='x',label=k)  # minima

            if pksonly is False:
                pks = np.asarray(peaks[k][0]).T # gets just maxima
            elif pksonly is True:
                pks = np.asarray(peaks[k]).T    # if peaks is already just maxima
            try:
                pkpos = pks[0]
            except:
                print "pks has wrong shape for k=",k
                print pks.shape
                continue
            #pl.scatter(int(k[1:])*np.ones_like(pkpos),pkpos,marker='*',label=k)  # maxima
        except:
            print "failed for ",k
            continue
    pl.legend()

def apply_hilbert(a, sig=None, full=False):
    """ Attempts to apply hilbert transform to a signal about a mean.
        First, smooth the signal, then subtract the smoothed signal.
        Apply hilbert to the residual, and add the smoothed signal back in.
    """
    assert a.ndim == 1, "Only works for 1d arrays"
    if sig is None:
        sig = a.size/10.
    if sig:
        a_smoothed = gaussian_filter(a, sig, mode='reflect')
    else:
        a_smoothed = a.mean()
    h = hilbert(a - a_smoothed)
    if full:
        return h, a_smoothed
    else:
        return np.abs(h) + a_smoothed

def gpeak_decay(peaks,f,pksonly=False):
    """ gpeak_decay(peaks,f)
    fits curve to the peaks in g(r)
    takes:
        peaks,  list of peak/valley positions and heights
        f,      the function for the curve, right now either:
                    exp_decay or powerlaw

    returns:
        popt, a tuple of parameters for f
        pcov, their covariances
    """
    if computer is 'foppl':
        print "cant do this on foppl"
        return
    if pksonly is False:
        maxima = dict([ (k, np.asarray(peaks[k][0])) for k in peaks])
        minima = dict([ (k, np.asarray(peaks[k][1])) for k in peaks])
    elif pksonly is True:
        maxima = peaks
    popt = {}
    pcov = {}
    pl.figure()
    for k in peaks:
        maximak = maxima[k].T
        print "k: f,maximak"
        print k,f,maximak
        if len(maxima[k]) > 1:
            popt[k],pcov[k] = curve_fit(f,maximak[0],maximak[1])
            fitrange = np.arange(min(maximak[0]),max(maximak[0]),.05)
            pl.plot(fitrange,f(fitrange,*popt[k]),'--',label='fit '+k)
        else:
            print "maximak empty:",maximak
    return popt,pcov

def exp_decay(s, sig=1., a=1., c=0):
    """ exp_decay(s,sigma,c,a)
        exponential decay function for fitting

        Args:
            s,  independent variable
        Params:
            sigma,  decay constant
            a,  prefactor
            c,  constant offset

        Returns:
            exp value at s
    """
    return c + a*np.exp(-s/sig)

def powerlaw(t, b=1., a=1., c=0):
    """ powerlaw(t,b,c,a)
        power law function for fitting

        Args:
            t,  independent variable
        Params:
            b,  exponent (power)
            a,  prefactor
            c,  constant offset
        Returns:
            power law value at t
    """
    return c + a * np.power(t, -b)

def log_decay(t, a=1, l=1., c=0.):
    return c - a*np.log(t/l)
    
def domyfits():
    if computer is 'foppl':
        print "cant do this on foppl"
        return
    for k in fixedpeaks:
        pl.figure()
        pl.plot(gdata[k]['rg'][:binmax]/22.0,gdata[k]['g'][:binmax]/22.0,',',label=k)
        pl.scatter(*np.asarray(fixedpeaks[k]).T,marker='o')
        pexps[k],cexp = curve_fit(corr.exp_decay,
                                  *np.array(fixedpeaks[k]).T, p0=(3,.0005,.0001))
        ppows[k],cpow = curve_fit(corr.powerlaw,
                                  *np.array(fixedpeaks[k]).T, p0=(-.5,.0005,.0001))
        xs = np.arange(0.8,10.4,0.2)
        pl.plot(xs,exp_decay(xs,*pexps[k]),label='exp_decay')
        pl.plot(xs,powerlaw(xs,*ppows[k]),label='powerlaw')
    return pexps, ppows


if __name__ == '__main__':
    prefix = 'n400'

    ss = 92#22  # side length of square in pixels
    rmax = ss*10.
    try:
        datapath = locdir+prefix+"_GR.npz"
        print "loading data from",datapath
        grnpz = np.load(datapath)
        g, dg, rg   = grnpz['g'], grnpz['dg'], grnpz['rg']
    except:
        print "NPZ file not found for n =",prefix[1:]
        datapath = locdir+prefix+'_results.txt'
        print "loading data from",datapath
        data = np.genfromtxt(datapath,
                skip_header = 1,
                usecols = [0,2,3,5],
                names   = "id,x,y,f",
                dtype   = [int,float,float,int])
        data['id'] -= 1 # data from imagej is 1-indexed
        print "\t...loaded"
        print "loading positions"
        gs, rgs = build_gs(data)
        print "\t...gs,rgs built"
        print "averaging over all frames..."
        g, dg, rg = avg_hists(gs, rgs)
        print "\t...averaged"
        print "saving data..."
        np.savez(locdir+prefix+"_GR",
                g  = np.asarray(g),
                dg = np.asarray(dg),
                rg = np.asarray(rg))
        print "\t...saved"

    binmax = len(rg[rg<rmax])
    #pl.figure()
    pl.plot(1.*rg[:binmax]/ss,g[:binmax],'.-',label=prefix)
    #pl.title("g[r],%s,dr%d"%(prefix,ss/2))
    pl.legend()
    #pl.show()
