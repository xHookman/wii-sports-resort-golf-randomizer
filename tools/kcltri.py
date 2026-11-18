def tri_vertices(k, p):
    # reconstruction standard KCL (Mario Kart Wii) : sommet A + normales d'aretes
    hgt, pi, fn, e1, e2, e3, attr = p
    A = k['verts'][pi]; N = k['nrms']
    def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def dot(a, b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    fnv, en1, en2, en3 = N[fn], N[e1], N[e2], N[e3]
    cA = cross(en1, fnv); cB = cross(en2, fnv)
    dB = hgt / dot(cB, en3); dC = hgt / dot(cA, en3)
    B = tuple(A[i] + cB[i] * dB for i in range(3))
    C = tuple(A[i] + cA[i] * dC for i in range(3))
    return A, B, C
