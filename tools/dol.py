import struct
d=open('/home/user/wsr/main.dol','rb').read()
off=struct.unpack('>18I',d[0:72]); addr=struct.unpack('>18I',d[72:144]); size=struct.unpack('>18I',d[144:216])
SEC=[(addr[i],size[i],off[i]) for i in range(18) if size[i]]
def a2o(a):
    for A,S,O in SEC:
        if A<=a<A+S: return O+a-A
    return None
def o2a(o):
    for A,S,O in SEC:
        if O<=o<O+S: return A+o-O
    return None
def u32(a): return struct.unpack('>I',d[a2o(a):a2o(a)+4])[0]
