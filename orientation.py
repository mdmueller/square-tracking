import matplotlib.pyplot as pl
import matplotlib.cm as cm
import numpy as np
#from scipy.stats import nanmean
from PIL import Image as Im

def get_fft(ifile=None,location=None):
    # FFT information from:
    # http://stackoverflow.com/questions/2652415/fft-and-array-to-image-image-to-array-conversion
    if ifile is None:
        ifile= "n20_bw_dots/n20_b_w_dots_0010.tif"
    if location is None:
        x = 424.66; y = 155.56; area = 125
        #x = 302.95; y = 221.87; area = 145
        #x = 386.27; y = 263.62; area = 141
        #x = 35.39; y = 305.92; area = 154
        location = x,y
    wdth = int(24 * np.sqrt(2))
    hght = wdth
    cropbox = map(int,(x - wdth/2., y - hght/2.,\
            x + wdth/2., y + hght/2.))
    i = Im.open(ifile)
    i = i.crop(cropbox)
    i.show()
    a = np.asarray(i)
    aa = np.gradient(a)
    b = np.fft.fft2(a)
    j = Im.fromarray(abs(b))
    ii = Im.fromarray(aa)
    if do_plots:
        ii.show()

    return b

def get_orientation(b):
    p = []
    for (mi,m) in enumerate(b):
        for (ni, n) in enumerate(m):
            ang = np.arctan2(mi - hght/2, ni - wdth/2)
            p.append([ang,abs(n)])
    p = np.asarray(p)
    p[:,0] = p[:,0] + np.pi
    slices = 45
    slicewidth = 2*np.pi/slices
    s = []
    for sl in range(slices):
        si = np.nonzero(abs(p[:,0] - sl*slicewidth) < slicewidth)
        sm = np.average(p[si,1])
        s.append([sl*slicewidth,sm])
    s = np.asarray(s)
    if do_plots:
        pl.figure()
        #pl.plot(p[:,0],p[:,1],'.',label='p')
        #pl.plot(s[:,0],s[:,1],'o',label='s')
        pl.plot(p[:,0]%(np.pi/2),p[:,1],'.',label='p')
        pl.plot(s[:,0]%(np.pi/2),s[:,1],'o',label='s')
        pl.legend()
        pl.show()
    return s, p

def find_corner(particle,corners,rc=11,drc=2):
    """
        looks in the given frame for the corner-marking dot closest to (and in
        appropriate range of) the particle

        arguments:
            particle - is particle position as (x,y) tuple
            corners  - is zipped list of positions of corner dots
                        as (x,y) vector tuples
            rc       - is the expected distance to corner from particle position
            drc      - delta r_c is the tolerance on rc

        returns:
            pcorner - position of corner that belongs to particle
            porient - particle orientation
    """
    from numpy.linalg import norm


    cdisps = np.array([
        (corner[0]-particle[0], corner[1]-particle[1])
        for corner in corners])
    cdists = np.array(map(norm, cdisps))
    legal = np.array(abs(cdists-rc) < drc, dtype=bool)

    if legal.sum() == 1:
        pcorner = tuple(np.asarray(corners)[legal].flatten())
        cdisp = cdisps[legal].flatten()
        print "Bingo: one corner found at {}".format(cdists[legal])
    elif legal.sum() > 1:
        print "Too many ({}) legal corners for this particle".format(legal.sum())
        legal = np.argmin(abs(cdists-rc))
        print "Using closest to rc = {} pixels at {}".format(rc, cdists[legal])
        pcorner = corners[legal]
        cdisp = cdisps[legal].flatten()
    else:
        #print "No legal corners for this particle"
        return None, None

    porient = np.arctan2(cdisp[1],cdisp[0]) % (2*np.pi)

    return pcorner,porient

def get_angles(data,cdata):#,framestep=100):
    if 's' in data.dtype.names:
        fieldnames = np.array(data.dtype.names)
        fieldnames[fieldnames == 's'] = 'f'
        data.dtype.names = tuple(fieldnames)
    if 's' in cdata.dtype.names:
        fieldnames = np.array(cdata.dtype.names)
        fieldnames[fieldnames == 's'] = 'f'
        cdata.dtype.names = tuple(fieldnames)
    #frames = np.arange(min(data['f']),max(data['f']),framestep)
    #postype = np.dtype()
    odata = np.zeros(len(data),dtype=[('pc',float,(2,)),('o',float)])
    orients = []
    for datum in data:
        #print "frame: {}, particle: {}".format(datum['f'],datum['id'])
        orients.append(find_corner(
                (datum['x'],datum['y']),
                zip(cdata['x'][cdata['f']==datum['f']],
                    cdata['y'][cdata['f']==datum['f']])
                )
        #odata['pc'], odata['o']
    return orients#odata





