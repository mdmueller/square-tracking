import numpy as np
#from scipy.stats import nanmean
from PIL import Image as Im

from socket import gethostname
hostname = gethostname()
if 'foppl' in hostname:
    computer = 'foppl'
    locdir = '/home/lawalsh/Granular/Squares/orientation/'
elif 'rock' in hostname:
    computer = 'rock'
    import matplotlib.pyplot as pl
    import matplotlib.cm as cm
    locdir = '/Users/leewalsh/Physics/Squares/orientation/'
else:
    print "computer not defined"
    print "where are you working?"

def field_rename(a,old,new):
    a.dtype.names = [ fn if fn != old else new for fn in a.dtype.names ]


def get_fft(ifile=None,location=None):
    """ get the fft of an image
        FFT information from:
        http://stackoverflow.com/questions/2652415/fft-and-array-to-image-image-to-array-conversion
    """
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
    """ get orientation from `b`, the fft of an image """
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
    if do_plots and computer is 'rock':
        pl.figure()
        #pl.plot(p[:,0],p[:,1],'.',label='p')
        #pl.plot(s[:,0],s[:,1],'o',label='s')
        pl.plot(p[:,0]%(np.pi/2),p[:,1],'.',label='p')
        pl.plot(s[:,0]%(np.pi/2),s[:,1],'o',label='s')
        pl.legend()
        pl.show()
    elif do_plots and computer is 'foppl':
        print "can't plot on foppl"
    return s, p

def find_corner(particle, corners, n=1, rc=11, drc=2, slr=True, multi=False):
    """ find_corner(particle, corners, **kwargs)

        looks in the given frame for the corner-marking dot closest to (and in
        appropriate range of) the particle

        arguments:
            particle - is particle position as (x,y) tuple
            corners  - is zipped list of positions of corner dots
                        as (x,y) vector tuples
            n        - number of corner dots
            rc       - is the expected distance to corner from particle position
            drc      - delta r_c is the tolerance on rc
            slr      - whether to use slr resolution
            multi    - whether to return data from all n dots
                           if not, average them

        returns:
            pcorner - position (x,y) of corner that belongs to particle
            porient - particle orientation (% 2pi)
            cdisp   - vector (x,y) from particle center to corner
    """
    from numpy.linalg import norm

    if slr:
        rc = 56; drc = 10

    particle = np.asarray(particle)
    corners = np.asarray(corners)
    cdisps = corners - particle
    cdists = np.sqrt((cdisps**2).sum(axis=1))
    legal = abs(cdists-rc) < drc

    N = legal.sum() # number of corners found
    if N < n:
        print N,"<",n
        return (None,)*3
    elif N == n:
        print N,"=",n
        pass
    elif N > n:
        print N,">",n
        # keep only the three closest to rc
        legal[np.argsort(abs(cdists-rc))[3:]] = False
    else:
        print 'whoops'
        return (None,)*3
    pcorner = corners[legal]
    cdisp = cdisps[legal]

    porient = np.arctan2(cdisp[:,1],cdisp[:,0]) % (2*np.pi)

    if multi:
        return pcorner, porient, cdisp
    else:
        return pcorner.mean(axis=0), porient.mean(axis=0), cdisp.mean(axis=0)

#TODO: use p.map() to find corners in parallel
# try splitting by frame first, use views for each frame
# or just pass a tuple of (datum, cdata[f==f]) to get_angle()

def get_angle((datum,cdata)):
    corner = find_corner(
            (datum['x'],datum['y']),
            zip(cdata['x'][cdata['f']==datum['f']],
                cdata['y'][cdata['f']==datum['f']])
            )
    dt = np.dtype([('corner',float,(2,)),('orient',float),('cdisp',float,(2,))])
    return np.array([corner], dtype=dt)

def get_angles_map(data,cdata,nthreads=None):
    """ get_angles(data, cdata, nthreads=None)
        
        arguments:
            data    - data array with 'x' and 'y' fields for particle centers
            cdata   - data array wity 'x' and 'y' fields for corners
            (these arrays need not have the same length,
                but both must have 'f' field for the image frame)
            nthreads - number of processing threads (cpu cores) to use
                None uses all cores of machine (8 for foppl, 2 for rock)
            
        returns:
            odata   - array with fields:
                'orient' for orientation of particles
                'corner' for particle corner (with 'x' and 'y' sub-fields)
            (odata has the same shape as data)
    """
    field_rename(data,'s','f')
    field_rename(cdata,'s','f')

    from multiprocessing import Pool
    if nthreads is None or nthreads > 8:
        nthreads = 8 if computer is 'foppl' else 2
    elif nthreads > 2 and computer is 'rock':
        nthreads = 2
    print "on {}, using {} threads".format(computer,nthreads)
    pool = Pool(nthreads)

    datums = [ (datum,cdata[cdata['f']==datum['f']])
                for datum in data ]
    odatalist = pool.map(get_angle, datums)
    odata = np.vstack(odatalist)
    return odata

def get_angles_loop(data, cdata, framestep=1, nc=3):
    """ get_angles(data, cdata, framestep=1, nc=3)
        
        arguments:
            data    - data array with 'x' and 'y' fields for particle centers
            cdata   - data array wity 'x' and 'y' fields for corners
            (these arrays need not have the same length,
                but both must have 'f' field for the image frame)
            framestep - only analyze every `framestep` frames
            nc      - number of corner dots
            
        returns:
            odata   - array with fields:
                'orient' for orientation of particles
                'corner' for particle corner (with 'x' and 'y' sub-fields)
            (odata has the same shape as data)
    """
    from correlation import get_id
    field_rename(data,'s','f')
    field_rename(cdata,'s','f')
    multi=False
    if nc == 3 and multi:
        dt = [('corner',float,(n,2,)),('orient',float,(n,)),('cdisp',float,(n,2,))]
    else:
        dt = [('corner',float,(2,)),('orient',float),('cdisp',float,(2,))]
    odata = np.zeros(len(data), dtype=dt)
    frame = 0
    for datum in data:
        if datum['f'] % framestep != 0:
            continue
        if frame != datum['f']:
            frame = datum['f']
            print 'frame',frame
        posi = (datum['x'],datum['y'])
        icorner, iorient, idisp = \
            find_corner(posi,
                        zip(cdata['x'][cdata['f']==datum['f']],
                            cdata['y'][cdata['f']==datum['f']]),
                        n=nc,multi=multi)

        iid = get_id(data,posi,datum['f'])
        imask = data['id']==iid
        odata['corner'][imask] = icorner
        odata['orient'][imask] = iorient
        odata['cdisp'][imask] = idisp
    return odata

def plot_orient_hist(odata,figtitle=''):
    if computer is not 'rock':
        print 'computer must be on rock'
        return False
    pl.figure()
    pl.hist(odata['orient'][np.isfinite(odata['orient'])], bins=90)
    pl.title('orientation histogram' if figtitle is '' else figtitle)
    return True

def plot_orient_map(data,odata,imfile='',mask=None):
    if computer is not 'rock':
        print 'computer must be on rock'
        return False
    import matplotlib.colors as mcolors
    import matplotlib.colorbar as mcolorbar
    pl.figure()
    if imfile is not None:
        bgimage = Im.open(extdir+prefix+'_0001.tif' if imfile is '' else imfile)
        pl.imshow(bgimage, cmap=cm.gray, origin='lower')
    #pl.quiver(X, Y, U, V, **kw)
    omask = np.isfinite(odata['orient'])
    if mask is None:
        mask=omask
    nz = mcolors.Normalize()
    nz.autoscale(data['f'][mask])
    qq = pl.quiver(data['y'][mask], data['x'][mask],
            odata['cdisp'][mask][:,1], odata['cdisp'][mask][:,0],
            color=cm.jet(nz(data['f'][mask])),
            scale=400.)
    cax,_ = mcolorbar.make_axes(pl.gca())
    cb = mcolorbar.ColorbarBase(cax, cmap=cm.jet, norm=nz)
    cb.set_label('time')
    return qq, cb

def plot_orient_time(data,odata,tracks):
    if computer is not 'rock':
        print 'computer must be on rock'
        return False

    omask = np.isfinite(odata['orient'])
    goodtracks = np.array([78,95,191,203,322])
    #tmask = np.in1d(tracks,goodtracks)
    pl.figure()
    for goodtrack in goodtracks:
        tmask = tracks == goodtrack
        fullmask = np.all(np.asarray(zip(omask,tmask)),axis=1)
        pl.plot(data['f'][fullmask],
                (odata['orient'][fullmask]
                 - odata['orient'][fullmask][np.argmin(data['f'][fullmask])]
                 + np.pi)%(2*np.pi),
                label="Track {}".format(goodtrack))
                #color=cm.jet(1.*tracks[fullmask]/max(tracks)))
                #color=cm.jet(1.*goodtrack/max(tracks)))
    for n in np.arange(0.5,2.0,0.5):
        pl.plot([0,1260],n*np.pi*np.array([1,1]),'k--')
    pl.legend()
    pl.title('Orientation over time\ninitial orientation = 0')
    pl.xlabel('frame (150fps)')
    pl.ylabel('orientation')

def plot_orient_location(data,odata,tracks):
    if computer is not 'rock':
        print 'computer must be on rock'
        return False
    import correlation as corr

    omask = np.isfinite(odata['orient'])
    goodtracks = np.array([78,95,191,203,322])

    ss = 22.

    pl.figure()
    for goodtrack in goodtracks:
        tmask = tracks == goodtrack
        fullmask = np.all(np.asarray(zip(omask,tmask)),axis=1)
        loc_start = (data['x'][fullmask][0],data['y'][fullmask][0])
        orient_start = odata['orient'][fullmask][0]
        sc = pl.scatter(
                (odata['orient'][fullmask] - orient_start + np.pi) % (2*np.pi),
                np.asarray(map(corr.get_norm,
                    zip([loc_start]*fullmask.sum(),
                        zip(data['x'][fullmask],data['y'][fullmask]))
                    ))/ss,
                #marker='*',
                label = 'track {}'.format(goodtrack),
                color = cm.jet(1.*goodtrack/max(tracks)))
                #color = cm.jet(1.*data['f'][fullmask]/1260.))
        print "track",goodtrack
    pl.legend()
    return True

