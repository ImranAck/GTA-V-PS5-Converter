"""Bounded vectorized equivalents of the original aligned-word and byte checks."""
from collections import Counter
import numpy as np

BLOCK = 1 << 20

def words(data, size):
    if not 0 <= size <= len(data):
        raise ValueError('invalid scan size')
    return np.frombuffer(data, dtype='<u8', count=size//8)

def pointer_in(data, size, low, high):
    a = words(data,size)
    if low >= high: return False
    return any(bool(np.any((b >= low) & (b < high))) for i in range(0,len(a),BLOCK) for b in (a[i:i+BLOCK],))

def aligned_targets(data, size, base, align):
    a=words(data,size); targets=set()
    for i in range(0,len(a),BLOCK):
        b=a[i:i+BLOCK]; v=b[(b>=base)&(b<base+size)&(b%align==0)]
        targets.update(int(x)-base for x in np.unique(v))
    return targets

def selected_counts(data, size, keys):
    a=words(data,size); keys=sorted(set(keys)); result=Counter()
    if not keys:return result
    k=np.array(keys,dtype='<u8')
    for i in range(0,len(a),BLOCK):
        b=a[i:i+BLOCK]; hits=b[np.isin(b,k,kind='sort')]
        vals,counts=np.unique(hits,return_counts=True)
        result.update({int(v):int(n) for v,n in zip(vals,counts)})
    return result

def diff_count(a,b):
    if len(a)!=len(b):raise ValueError('different byte lengths')
    x=np.frombuffer(a,dtype=np.uint8); y=np.frombuffer(b,dtype=np.uint8)
    return sum(int(np.count_nonzero(x[i:i+BLOCK]!=y[i:i+BLOCK])) for i in range(0,len(x),BLOCK))

def changed_outside(a,b,size,allowed):
    if size<0 or size>min(len(a),len(b)):raise ValueError('invalid comparison size')
    x=np.frombuffer(a,dtype=np.uint8,count=size);y=np.frombuffer(b,dtype=np.uint8,count=size)
    # Union of original allowed byte ranges, without building a set per byte.
    merged=[]
    for start,end in sorted((max(0,s),min(size,e)) for s,e in allowed):
        if start>=end:continue
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        else:merged.append((start,end))
    pos=0
    for start,end in merged+[(size,size)]:
        if pos<start and not np.array_equal(x[pos:start],y[pos:start]):return True
        pos=end
    return False
