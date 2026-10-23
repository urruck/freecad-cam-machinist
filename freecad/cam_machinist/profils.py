# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# CAM Machinist · FabLab Le Boc@l, Centre Social et Socioculturel du Chemillois
"""Profils machine (cotes + modèle STEP de broche) et outils d'alignement du STEP.

Un profil est un dossier contenant profil.json et, s'il y a un modèle de
broche, la copie du fichier d'origine et la forme alignée (broche.brep).
Profils fournis : resources/machines/<id>/ (lecture seule).
Profils de l'utilisateur·ice : <dossier utilisateur FreeCAD>/CAMMachinist/machines/<id>/.
Un profil utilisateur de même identifiant remplace le profil fourni.
"""

import json
import math
import os
import re
import shutil
import unicodedata
import zipfile

import FreeCAD as App
import Part
import numpy as np

from . import moteur

FORMAT = 1
ICI = os.path.dirname(os.path.abspath(__file__))
DOSSIER_FOURNI = os.path.join(ICI, "resources", "machines")
EXTENSIONS_MODELE = (".step", ".stp", ".iges", ".igs", ".brep", ".brp")


def dossier_utilisateur():
    d = os.path.join(App.getUserAppDataDir(), "CAMMachinist", "machines")
    os.makedirs(d, exist_ok=True)
    return d


def identifiant(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "machine"


def lister():
    """{id: {"nom", "dossier", "fourni"}} ; les profils utilisateur priment."""
    out = {}
    for base, fourni in ((DOSSIER_FOURNI, True), (dossier_utilisateur(), False)):
        if not os.path.isdir(base):
            continue
        for ident in sorted(os.listdir(base)):
            f = os.path.join(base, ident, "profil.json")
            if not os.path.isfile(f):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    nom = json.load(fh).get("nom", ident)
            except Exception as e:
                moteur.avert("Profil illisible %s : %s" % (f, e))
                continue
            out[ident] = {"nom": nom, "dossier": os.path.join(base, ident), "fourni": fourni}
    return out


def charger(ident):
    info = lister().get(ident)
    if info is None:
        return None
    with open(os.path.join(info["dossier"], "profil.json"), encoding="utf-8") as fh:
        prof = json.load(fh)
    prof["params"] = moteur.completer_params(prof.get("params"))
    prof["_id"] = ident
    prof["_dossier"] = info["dossier"]
    prof["_fourni"] = info["fourni"]
    return prof


def nouveau(nom="Nouvelle machine"):
    return {"format": FORMAT, "nom": nom, "description": "", "params": moteur.params_defaut(), "broche": None}


def enregistrer(prof, ident=None, modele_en_attente=None):
    """Écrit le profil dans le dossier utilisateur. modele_en_attente : résultat de
    preparer_modele() à enregistrer avec le profil, ou "retirer"."""
    ident = ident or prof.get("_id") or identifiant(prof["nom"])
    dest = os.path.join(dossier_utilisateur(), ident)
    ancien = prof.get("_dossier")
    os.makedirs(dest, exist_ok=True)
    broche = dict(prof["broche"]) if prof.get("broche") else None

    # fichiers du modèle existant : recopiés si le profil vient d'ailleurs (profil fourni, autre id)
    if broche and modele_en_attente is None and ancien and os.path.abspath(ancien) != os.path.abspath(dest):
        for cle in ("source", "forme"):
            f = broche.get(cle)
            if f and os.path.isfile(os.path.join(ancien, f)):
                shutil.copy2(os.path.join(ancien, f), os.path.join(dest, f))

    if modele_en_attente == "retirer":
        broche = None
    elif modele_en_attente is not None:
        m = modele_en_attente
        ext = os.path.splitext(m["source"])[1].lower() or ".step"
        nom_source = "broche_source" + ext
        if os.path.abspath(m["source"]) != os.path.abspath(os.path.join(dest, nom_source)):
            shutil.copy2(m["source"], os.path.join(dest, nom_source))
        m["forme"].exportBrep(os.path.join(dest, "broche.brep"))
        broche = {
            "source": nom_source,
            "fichier_origine": os.path.basename(m.get("nom_origine") or m["source"]),
            "forme": "broche.brep",
            "alignement": placement_vers_json(m["alignement"]),
            "inclut_coulisse": bool(m["inclut_coulisse"]),
            "couper_sous_nez": bool(m["couper_sous_nez"]),
            "enveloppe": [list(p) for p in m["enveloppe"]],
        }
    data = {
        "format": FORMAT,
        "nom": prof["nom"],
        "description": prof.get("description", ""),
        "params": {k: prof["params"][k] for k in moteur.params_defaut()},
        "broche": broche,
    }
    with open(os.path.join(dest, "profil.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    _CACHE.clear()
    return ident


def supprimer(ident):
    info = lister().get(ident)
    if info and not info["fourni"]:
        shutil.rmtree(info["dossier"], ignore_errors=True)
        _CACHE.clear()
        return True
    return False


def exporter_zip(ident, chemin):
    info = lister()[ident]
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(info["dossier"])):
            p = os.path.join(info["dossier"], f)
            if os.path.isfile(p):
                z.write(p, os.path.join(ident, f))


def importer_zip(chemin):
    """Importe un profil exporté. Renvoie son identifiant."""
    with zipfile.ZipFile(chemin) as z:
        noms = [n for n in z.namelist() if n.endswith("profil.json")]
        if not noms:
            raise ValueError("Pas de profil.json dans l'archive.")
        racine = os.path.dirname(noms[0])
        with z.open(noms[0]) as fh:
            data = json.loads(fh.read().decode("utf-8"))
        ident = identifiant(racine or data.get("nom", "machine"))
        dest = os.path.join(dossier_utilisateur(), ident)
        os.makedirs(dest, exist_ok=True)
        for n in z.namelist():
            if n.endswith("/") or os.path.dirname(n) != racine:
                continue
            base = os.path.basename(n)
            if base != "profil.json" and not base.lower().endswith(EXTENSIONS_MODELE):
                continue
            with z.open(n) as src, open(os.path.join(dest, base), "wb") as dst:
                shutil.copyfileobj(src, dst)
    _CACHE.clear()
    return ident


# =============================================================================
#  Chargement du modèle de broche d'un profil
# =============================================================================

_CACHE = {}


def modele(prof):
    """ModeleBroche du profil, ou None (broche dessinée à partir des cotes)."""
    b = (prof or {}).get("broche")
    if not b or not prof.get("_dossier"):
        return None
    chemin = os.path.join(prof["_dossier"], b.get("forme", "broche.brep"))
    if not os.path.isfile(chemin):
        moteur.avert("Modèle de broche introuvable (%s) : broche dessinée à partir des cotes." % chemin)
        return None
    cle = (chemin, os.path.getmtime(chemin))
    if cle not in _CACHE:
        sh = Part.Shape()
        sh.read(chemin)
        _CACHE[cle] = sh
    prims = b.get("enveloppe") or []
    if not prims:
        prims = enveloppe(_CACHE[cle], zmin=0.0 if b.get("couper_sous_nez") else None)
    return moteur.ModeleBroche(_CACHE[cle], prims, b.get("inclut_coulisse", False),
                               nom=b.get("fichier_origine", ""))


# =============================================================================
#  Alignement d'un modèle importé
# =============================================================================

def lire_modele(chemin):
    sh = Part.Shape()
    sh.read(chemin)
    if sh.isNull() or not sh.Faces:
        raise ValueError("Le fichier ne contient pas de surfaces exploitables.")
    return sh


def placement_vers_json(pl):
    q = pl.Rotation.Q
    return {"base": [pl.Base.x, pl.Base.y, pl.Base.z], "rotation": [q[0], q[1], q[2], q[3]]}


def placement_depuis_json(d):
    if not d:
        return App.Placement()
    return App.Placement(App.Vector(*d["base"]), App.Rotation(*d["rotation"]))


def repere_selection(sub):
    """(centre, axe) d'une arête circulaire ou d'une face plane, en coordonnées globales."""
    if isinstance(sub, Part.Edge):
        c = sub.Curve
        if hasattr(c, "Center") and hasattr(c, "Radius") and hasattr(c, "Axis"):
            return App.Vector(c.Center), App.Vector(c.Axis)
        raise ValueError("Cette arête n'est pas un cercle : choisir le bord circulaire du nez de broche.")
    if isinstance(sub, Part.Face):
        surf = sub.Surface
        if surf.__class__.__name__ == "Plane":
            u0, u1, v0, v1 = sub.ParameterRange
            return App.Vector(sub.CenterOfMass), sub.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        if hasattr(surf, "Axis") and hasattr(surf, "Center") and hasattr(surf, "Radius"):
            # face cylindrique : axe du cylindre, centre au bas de la face le long de l'axe
            ax = App.Vector(surf.Axis)
            ax.normalize()
            pts = [v.Point for v in sub.Vertexes] or [sub.CenterOfMass]
            t = [(p - surf.Center).dot(ax) for p in pts]
            return surf.Center + ax * min(t), ax
        raise ValueError("Choisir une arête circulaire ou une face plane du nez de broche.")
    raise ValueError("Choisir une arête circulaire ou une face plane du nez de broche.")


def aligner(alignement, forme_globale_bbox_centre, centre, axe):
    """Nouvel alignement : le centre choisi va en (0, 0, 0), l'axe vers +Z côté corps de broche."""
    a = App.Vector(axe)
    a.normalize()
    if (forme_globale_bbox_centre - centre).dot(a) < 0:
        a = a * -1
    r = App.Rotation(a, App.Vector(0, 0, 1))
    t = App.Placement(r.multVec(centre) * -1, r)
    return t.multiply(alignement)


def equerrer(forme_canonique, alignement):
    """Tourne autour de Z pour mettre les flancs plats du corps de broche d'équerre avec X et Y.
    Sans flanc plat (broche ronde), minimise l'encombrement vu de dessus."""
    somme = 0j
    total = 0.0
    for f in forme_canonique.Faces:
        if f.Surface.__class__.__name__ != "Plane":
            continue
        try:
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        except Exception:
            continue
        if abs(n.z) > 0.1:
            continue
        a = math.atan2(n.y, n.x)
        somme += f.Area * complex(math.cos(4 * a), math.sin(4 * a))
        total += f.Area
    if total > 0 and abs(somme) > 0.3 * total:
        theta = math.degrees(math.atan2(somme.imag, somme.real)) / 4.0
    else:
        pts, _t = forme_canonique.tessellate(max(forme_canonique.BoundBox.DiagonalLength / 500.0, 0.2))
        if not pts:
            return alignement
        P = np.array([(p.x, p.y) for p in pts])
        meilleur, theta = None, 0.0
        for deg in np.arange(0.0, 90.0, 1.0):
            r = math.radians(deg)
            x = P[:, 0] * math.cos(r) - P[:, 1] * math.sin(r)
            y = P[:, 0] * math.sin(r) + P[:, 1] * math.cos(r)
            aire = (x.max() - x.min()) * (y.max() - y.min())
            if meilleur is None or aire < meilleur - 1e-6:
                meilleur, theta = aire, -deg
    if abs(theta) < 0.01:
        return alignement
    return tourner(alignement, -theta)


def orienter_bride(forme_canonique, alignement):
    """Tourne autour de Z pour mettre le côté le plus chargé (bride, fixation) vers +X (côté poutre)."""
    bb = forme_canonique.BoundBox
    cx, cy = (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2
    if max(abs(cx), abs(cy)) < 3.0:
        return alignement
    k = int(round(math.degrees(math.atan2(cy, cx)) / 90.0))
    return tourner(alignement, -90.0 * k)


def tourner(alignement, angle):
    return App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), angle)).multiply(alignement)


def retourner(alignement):
    return App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180)).multiply(alignement)


def decaler_z(alignement, dz):
    return App.Placement(App.Vector(0, 0, dz), App.Rotation()).multiply(alignement)


def forme_alignee(source, alignement):
    s = source.copy()
    s.Placement = alignement.multiply(s.Placement)
    return s


def preparer_modele(chemin_source, source, alignement, inclut_coulisse, couper_sous_nez, nom_origine=None):
    """Forme canonique (coupée sous le nez si demandé) et enveloppe de contrôle."""
    s = forme_alignee(source, alignement)
    affichage = s
    if couper_sous_nez:
        bb = s.BoundBox
        L = 4 * max(bb.DiagonalLength, 1.0)
        try:
            c = s.common(Part.makeBox(L, L, L, App.Vector(-L / 2, -L / 2, 0)))
            if not c.isNull() and c.Faces:
                affichage = c
        except Exception as e:
            moteur.avert("Découpe sous le nez impossible (%s) : modèle affiché entier." % e)
    env = enveloppe(s, zmin=0.0 if couper_sous_nez else None)
    return {"source": chemin_source, "nom_origine": nom_origine, "forme": affichage, "alignement": alignement,
            "inclut_coulisse": inclut_coulisse, "couper_sous_nez": couper_sous_nez, "enveloppe": env}


# =============================================================================
#  Enveloppe de contrôle 2,5D d'un modèle quelconque
# =============================================================================

def enveloppe(forme, pas=2.0, fusion=3.0, zmin=None, max_volumes=16):
    """Découpe le modèle en tranches horizontales et le remplace par quelques pavés ou cylindres
    verticaux qui le contiennent entièrement (approximation par excès, jamais par défaut).
    L'écart maximal ajouté sur le côté est de l'ordre de « fusion »."""
    bb = forme.BoundBox
    tol = min(max(bb.DiagonalLength / 1000.0, 0.1), 1.0)
    pts, tris = forme.tessellate(tol)
    if not pts or not tris:
        return [("box", (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2, bb.XLength / 2, bb.YLength / 2,
                 bb.ZMin, bb.ZMax, 0.0)]
    V = np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float64)
    T = np.array(tris, dtype=np.int64)
    E = np.unique(np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1), axis=0)
    A, B = V[E[:, 0]], V[E[:, 1]]

    def points(a, b):
        morceaux = [V[(V[:, 2] >= a) & (V[:, 2] <= b), :2]]
        za, zb = A[:, 2], B[:, 2]
        for c in (a, b):
            k = (za - c) * (zb - c) < 0
            if k.any():
                t = (c - za[k]) / (zb[k] - za[k])
                morceaux.append(A[k, :2] + t[:, None] * (B[k, :2] - A[k, :2]))
        return np.concatenate(morceaux)

    z0 = bb.ZMin if zmin is None else max(bb.ZMin, zmin)
    z1 = bb.ZMax
    if z1 - z0 < 1e-6:
        z1 = z0 + 0.01
    n = int(min(max(math.ceil((z1 - z0) / pas), 1), 400))
    niveaux = np.linspace(z0, z1, n + 1)
    tranches = []
    for a, b in zip(niveaux[:-1], niveaux[1:]):
        P = points(a, b)
        if len(P):
            tranches.append((a, b, P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max()))
    if not tranches:
        return []

    def grouper(tol_fusion):
        groupes = []
        for t in tranches:
            g = groupes[-1] if groupes else None
            if (g is not None and t[0] <= g["b"] + 1e-6
                    and t[2] >= g["ref"][0] - tol_fusion and t[3] <= g["ref"][1] + tol_fusion
                    and t[4] >= g["ref"][2] - tol_fusion and t[5] <= g["ref"][3] + tol_fusion):
                g["b"] = t[1]
                g["bb"] = [min(g["bb"][0], t[2]), max(g["bb"][1], t[3]), min(g["bb"][2], t[4]), max(g["bb"][3], t[5])]
            else:
                groupes.append({"a": t[0], "b": t[1], "ref": t[2:6], "bb": list(t[2:6])})
        return groupes

    f = fusion
    groupes = grouper(f)
    while len(groupes) > max_volumes:
        f *= 1.6
        groupes = grouper(f)

    prims = []
    for g in groupes:
        x0, x1, y0, y1 = g["bb"]
        cx, cy, hx, hy = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        P = points(g["a"], g["b"])
        r = float(np.max(np.hypot(P[:, 0] - cx, P[:, 1] - cy))) if len(P) else max(hx, hy)
        if math.pi * r * r < 0.98 * 4 * hx * hy:
            prims.append(("cyl", cx, cy, r, r, float(g["a"]), float(g["b"]), 0.0))
        else:
            prims.append(("box", cx, cy, hx, hy, float(g["a"]), float(g["b"]), 0.0))
    return prims


def ecart_enveloppe(forme, prims):
    """Volume de l'enveloppe rapporté au volume englobant du modèle (indicateur de serrage)."""
    v = 0.0
    for k, _cx, _cy, hx, hy, z0, z1, _a in prims:
        v += (math.pi * hx * hx if k == "cyl" else 4 * hx * hy) * (z1 - z0)
    bb = forme.BoundBox
    return v / max(bb.XLength * bb.YLength * bb.ZLength, 1e-9)


def reprendre_tableur(doc):
    """Cotes lues dans le tableur « MachineParams » de l'ancienne macro Excitech, s'il existe."""
    sh = doc.getObject("MachineParams") if doc is not None else None
    if sh is None:
        return None
    out = {}
    for alias in moteur.params_defaut():
        try:
            cell = sh.getCellFromAlias(alias)
            if cell:
                v = sh.get(cell)
                out[alias] = float(getattr(v, "Value", v))
        except Exception:
            pass
    return out or None
