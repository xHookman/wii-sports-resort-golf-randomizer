import re,sys
def xrefs(targets, asm='/home/user/wsr/text1.asm'):
    reg={}; hits=[]
    pat=re.compile(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(\S+)\s*(.*)$')
    for line in open(asm):
        m=pat.match(line)
        if not m: continue
        a=int(m.group(1),16); op=m.group(2); args=m.group(3).replace(' ','').split(',')
        try:
            if op=='lis': reg[args[0]]=(int(args[1],0)&0xffff)<<16
            elif op=='addi' and args[1] in reg:
                v=(reg[args[1]]+int(args[2],0))&0xffffffff; reg[args[0]]=v
                if v in targets: hits.append((a,v))
            elif op=='ori' and args[1] in reg:
                v=reg[args[1]]|int(args[2],0); reg[args[0]]=v
                if v in targets: hits.append((a,v))
            elif op=='mr' and args[1] in reg: reg[args[0]]=reg[args[1]]
            elif op in ('stwu','bl','blr','bctrl'): pass
        except Exception: pass
    return hits
