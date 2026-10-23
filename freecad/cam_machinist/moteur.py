# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# CAM Machinist · FabLab Le Boc@l, Centre Social et Socioculturel du Chemillois
"""Moteur : géométrie de la machine, lecture du parcours d'outil, contrôle des collisions.

Repère : celui du Job CAM. La pose de référence de la tête place la pointe de
l'outil en (0, 0, 0) ; chaque corps est ensuite translaté selon sa mobilité
(fixe, portique, chariot, z).

Primitive de collision : (type, cx, cy, hx, hy, z0, z1, anneau), type « box »
(pavé vertical) ou « cyl » (cylindre vertical, rayon hx).
"""

import math

import FreeCAD as App
import Part
import numpy as np

PREFIXE = "CMach_"
NOM_GROUPE = "Machine_CAMMachinist"
NOM_BRIDAGE = "Bridage"
NOM_COLLISIONS = "Collisions_CAMMachinist"
GROUPE_PROPS = "CAM Machinist"

# -----------------------------------------------------------------------------
#  Paramètres de la machine (enregistrés dans le profil)
#  (section, alias, défaut, unité, description)
# -----------------------------------------------------------------------------
PARAMS = [
    ("Table", None, None, None, None),
    ("", "TableX", 1600, "mm", "Dimension de la table selon X"),
    ("", "TableY", 3100, "mm", "Dimension de la table selon Y"),
    ("", "TableEp", 60, "mm", "Épaisseur dessinée de la table (martyr compris)"),

    ("Courses (depuis le coin de table)", None, None, None, None),
    ("", "CourseXmin", 0, "mm", "Axe broche : X mini atteignable"),
    ("", "CourseXmax", 1530, "mm", "Axe broche : X maxi atteignable"),
    ("", "CourseYmin", 0, "mm", "Axe broche : Y mini atteignable"),
    ("", "CourseYmax", 3050, "mm", "Axe broche : Y maxi atteignable"),
    ("", "NezHautMax", 260, "mm", "Hauteur du nez de broche au-dessus de la table, Z en butée haute"),
    ("", "CourseZ", 200, "mm", "Course utile en Z"),

    ("Portique", None, None, None, None),
    ("", "AxePortique", 1, "0/1", "1 = le portique avance en Y (grand côté en Y), 0 = il avance en X"),
    ("", "SensPoutre", 1, "+1/-1", "+1 = poutre côté + de l'axe portique par rapport à la broche, -1 = côté -"),
    ("", "PassageSousPortique", 200, "mm", "Hauteur libre entre table et dessous de poutre"),
    ("", "DecalagePoutre", 220, "mm", "Distance axe broche → face avant de la poutre"),
    ("", "PoutreLargeur", 260, "mm", "Épaisseur de la poutre (selon l'axe portique)"),
    ("", "PoutreHauteur", 320, "mm", "Hauteur de la poutre"),
    ("", "PoutreLongueur", 2000, "mm", "Longueur de la poutre entre montants"),
    ("", "MontantLargeur", 400, "mm", "Largeur des montants (selon l'axe portique)"),
    ("", "MontantEpaisseur", 100, "mm", "Épaisseur des montants"),
    ("", "MontantBas", 250, "mm", "Descente des montants sous le dessous de table (dessin)"),

    ("Chariot et coulisse Z", None, None, None, None),
    ("", "ChariotEpaisseur", 60, "mm", "Épaisseur du chariot (plaque sur la poutre)"),
    ("", "ChariotLargeur", 300, "mm", "Largeur du chariot le long de la poutre"),
    ("", "ChariotDebordBas", 60, "mm", "Descente du chariot sous le dessous de poutre"),
    ("", "CoulisseEpaisseur", 40, "mm", "Épaisseur de la coulisse Z"),
    ("", "CoulisseLargeur", 220, "mm", "Largeur de la coulisse Z"),
    ("", "CoulisseHaut", 500, "mm", "Hauteur de la coulisse Z"),
    ("", "CoulisseBas", 40, "mm", "Bas de la coulisse au-dessus du nez de broche (négatif si plus bas)"),

    ("Broche dessinée (si pas de modèle STEP)", None, None, None, None),
    ("", "BrocheNezDiam", 120, "mm", "Diamètre du nez de broche"),
    ("", "BrocheNezHaut", 25, "mm", "Hauteur du nez de broche"),
    ("", "BrocheLargeur", 170, "mm", "Corps de broche, cote le long de la poutre"),
    ("", "BrocheProfondeur", 170, "mm", "Corps de broche, cote vers la poutre"),
    ("", "BrocheLongueur", 380, "mm", "Corps de broche, hauteur au-dessus du nez"),

    ("Porte-outil et outil (défauts, réglables par outil)", None, None, None, None),
    ("", "Jauge", 110, "mm", "Nez de broche → pointe de l'outil"),
    ("", "Sortie", 30, "mm", "Longueur d'outil qui dépasse de l'écrou"),
    ("", "EcrouDiam", 50, "mm", "Diamètre de l'écrou de pince (ER32 : 50)"),
    ("", "EcrouHaut", 22, "mm", "Hauteur de l'écrou de pince"),
    ("", "PorteOutilDiam", 50, "mm", "Diamètre du porte-outil entre écrou et nez"),
    ("", "OutilDiam", 6, "mm", "Diamètre d'outil si le Tool Controller n'en donne pas"),

    ("Hotte d'aspiration", None, None, None, None),
    ("", "HotteActive", 1, "0/1", "1 = hotte montée"),
    ("", "HotteDiam", 220, "mm", "Diamètre extérieur de la hotte"),
    ("", "HotteHaut", 90, "mm", "Hauteur de la hotte, brosses comprises"),
    ("", "HotteBas", 60, "mm", "Descente du bas des brosses sous le nez de broche"),

    ("Contrôle", None, None, None, None),
    ("", "PasEchantillon", 5, "mm", "Pas de découpage du parcours"),
    ("", "ResolutionGrille", 4, "mm", "Taille des cases de la carte des obstacles"),
    ("", "MargeSecurite", 2, "mm", "Garde minimale demandée"),
    ("", "TolerancePlateau", 1, "mm", "Profondeur d'outil tolérée dans la table / le martyr"),
    ("", "BudgetExact", 4000, "", "Nombre maxi de vérifications géométriques fines par contrôle"),
]

# Mise en place, propre à chaque Job (propriétés du Job)
MISE_EN_PLACE = [
    ("CMachOrigineX", "OrigineX", 20.0, "Position du X0 du Job depuis le coin de table"),
    ("CMachOrigineY", "OrigineY", 20.0, "Position du Y0 du Job depuis le coin de table"),
    ("CMachTableAuto", "TableZAuto", 1.0, "Dessus de table pris sous le brut du Job"),
    ("CMachTableZ", "TableZ", 0.0, "Z du dessus de table si le réglage automatique est coupé"),
]

COULEURS = {
    "table": (0.78, 0.70, 0.55),
    "portique": (0.55, 0.57, 0.60),
    "chariot": (0.40, 0.42, 0.45),
    "broche": (0.718, 0.110, 0.110),      # rouge Boc@l #B71C1C
    "acier": (0.78, 0.78, 0.80),
    "outil": (0.95, 0.75, 0.10),
    "hotte": (0.20, 0.35, 0.60),
    "alerte": (1.00, 0.45, 0.00),
}

GRAVITES = ["COLLISION", "COURSE", "FRÔLEMENT", "À VÉRIFIER", "BROSSE"]

# (classe de corps, catégorie d'obstacle, gravité, marge)
REGLES = [
    ("outil", "bridage", "COLLISION", "marge"),
    ("outil", "table", "COLLISION", "plateau"),
    ("basse", "bridage", "COLLISION", "marge"),
    ("basse", "table", "COLLISION", "marge"),
    ("basse", "piece", "COLLISION", "marge"),
    ("basse", "brut", "À VÉRIFIER", "marge"),
    ("haute", "bridage", "COLLISION", "marge"),
    ("haute", "table", "COLLISION", "marge"),
    ("haute", "piece", "COLLISION", "marge"),
    ("haute", "brut", "COLLISION", "marge"),
    ("hotte", "bridage", "BROSSE", "zero"),
    ("hotte", "table", "BROSSE", "zero"),
]

NOMS_OBSTACLES = {"table": "table", "bridage": "bridage", "piece": "pièce", "brut": "brut"}


def log(msg):
    App.Console.PrintMessage("[CAM Machinist] " + msg + "\n")


def avert(msg):
    App.Console.PrintWarning("[CAM Machinist] " + msg + "\n")


def params_defaut():
    return {a: float(d) for _s, a, d, _u, _x in PARAMS if a}


def completer_params(p):
    """Paramètres d'un profil complétés par les défauts (profil d'une version antérieure)."""
    P = params_defaut()
    for k, v in (p or {}).items():
        try:
            P[k] = float(v)
        except (TypeError, ValueError):
            pass
    return P


def verifier_params(P, modele=None):
    msgs = []
    if P["Jauge"] < P["Sortie"] + P["EcrouHaut"]:
        msgs.append("Jauge < Sortie + EcrouHaut : l'écrou rentrerait dans la broche.")
    face = P["DecalagePoutre"] - P["ChariotEpaisseur"] - P["CoulisseEpaisseur"]
    if modele is None and face < P["BrocheProfondeur"] / 2:
        msgs.append("La broche traverse la coulisse : augmenter DecalagePoutre ou réduire BrocheProfondeur.")
    tv = P["TableY"] if P["AxePortique"] < 0.5 else P["TableX"]
    if P["PoutreLongueur"] <= tv:
        msgs.append("La poutre est plus courte que la table : les montants seraient sur la table.")
    return msgs


# =============================================================================
#  Modèle STEP de la broche
# =============================================================================

class ModeleBroche(object):
    """Broche importée, dans le repère canonique : nez de broche en (0, 0, 0),
    outil vers -Z, côté poutre vers +X."""

    def __init__(self, forme, prims, inclut_coulisse=False, nom=""):
        self.forme = forme
        self.prims = [tuple(p) for p in prims]
        self.inclut_coulisse = bool(inclut_coulisse)
        self.nom = nom


def axe_portique(P):
    return 0 if P["AxePortique"] < 0.5 else 1


def angle_canonique(P):
    """Rotation (degrés, autour de Z) du repère canonique vers la machine."""
    s = 1.0 if P["SensPoutre"] >= 0 else -1.0
    if axe_portique(P) == 0:
        return 0.0 if s > 0 else 180.0
    return 90.0 if s > 0 else 270.0


def tourner_prims(prims, angle, dz):
    q = int(round(angle / 90.0)) % 4
    out = []
    for k, cx, cy, hx, hy, z0, z1, anneau in prims:
        for _ in range(q):
            cx, cy, hx, hy = -cy, cx, hy, hx
        out.append((k, cx, cy, hx, hy, z0 + dz, z1 + dz, anneau))
    return out


def placer_forme(forme, angle, dz):
    s = forme.copy()
    pl = App.Placement(App.Vector(0, 0, dz), App.Rotation(App.Vector(0, 0, 1), angle))
    s.Placement = pl.multiply(s.Placement)
    return Part.makeCompound([s])


# =============================================================================
#  Géométrie de la machine
# =============================================================================

def corps(P, cfg, zt, modele=None):
    """Corps de la machine pour un réglage d'outil cfg = (jauge, sortie, rayon)."""
    jauge, sortie, rayon = cfg
    s = 1.0 if P["SensPoutre"] >= 0 else -1.0
    axe = axe_portique(P)

    def pave(u0, u1, v0, v1, z0, z1):
        a, b = sorted((s * u0, s * u1))
        if axe == 0:
            x0, x1, y0, y1 = a, b, v0, v1
        else:
            x0, x1, y0, y1 = v0, v1, a, b
        return ("box", (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, z0, z1, 0.0)

    def cyl(r, z0, z1, anneau=0.0):
        return ("cyl", 0.0, 0.0, r, r, z0, z1, anneau)

    if axe == 0:
        tv, ov = P["TableY"], P["OrigineY"]
    else:
        tv, ov = P["TableX"], P["OrigineX"]
    vc = tv / 2 - ov                       # milieu de table le long de la poutre

    zb = zt + P["PassageSousPortique"]     # dessous de poutre
    dec, W, H, L = P["DecalagePoutre"], P["PoutreLargeur"], P["PoutreHauteur"], P["PoutreLongueur"]
    CE, KE = P["ChariotEpaisseur"], P["CoulisseEpaisseur"]

    out = []
    tx, ty = P["TableX"], P["TableY"]
    out.append(dict(nom="Table", label="Table", cls=None, mob="fixe", coul="table", transp=0,
                    prims=[("box", tx / 2 - P["OrigineX"], ty / 2 - P["OrigineY"], tx / 2, ty / 2,
                            zt - P["TableEp"], zt, 0.0)]))

    out.append(dict(nom="Poutre", label="Portique · poutre", cls="haute", mob="portique",
                    coul="portique", transp=45,
                    prims=[pave(dec, dec + W, vc - L / 2, vc + L / 2, zb, zb + H)]))

    uc, ML, ME = dec + W / 2, P["MontantLargeur"], P["MontantEpaisseur"]
    zbas = zt - P["TableEp"] - P["MontantBas"]
    out.append(dict(nom="Montants", label="Portique · montants", cls="haute", mob="portique",
                    coul="portique", transp=45,
                    prims=[pave(uc - ML / 2, uc + ML / 2, vc - L / 2 - ME, vc - L / 2, zbas, zb + H),
                           pave(uc - ML / 2, uc + ML / 2, vc + L / 2, vc + L / 2 + ME, zbas, zb + H)]))

    CL = P["ChariotLargeur"]
    out.append(dict(nom="Chariot", label="Chariot", cls="haute", mob="chariot", coul="chariot", transp=20,
                    prims=[pave(dec - CE, dec, -CL / 2, CL / 2, zb - P["ChariotDebordBas"], zb + H)]))

    if modele is None or not modele.inclut_coulisse:
        KL = P["CoulisseLargeur"]
        zc0 = jauge + P["CoulisseBas"]
        out.append(dict(nom="Coulisse", label="Coulisse Z", cls="haute", mob="z", coul="chariot", transp=20,
                        prims=[pave(dec - CE - KE, dec - CE, -KL / 2, KL / 2, zc0, zc0 + P["CoulisseHaut"])]))

    if modele is not None:
        ang = angle_canonique(P)
        out.append(dict(nom="Broche", label="Broche (modèle %s)" % (modele.nom or "STEP"), cls="haute",
                        mob="z", coul="broche", transp=0,
                        prims=tourner_prims(modele.prims, ang, jauge),
                        forme=placer_forme(modele.forme, ang, jauge)))
    else:
        n0, n1 = jauge, jauge + P["BrocheNezHaut"]
        b1 = n1 + P["BrocheLongueur"]
        BP, BL = P["BrocheProfondeur"], P["BrocheLargeur"]
        uf = dec - CE - KE
        prims = [cyl(P["BrocheNezDiam"] / 2, n0, n1), pave(-BP / 2, BP / 2, -BL / 2, BL / 2, n1, b1)]
        if uf > BP / 2:
            prims.append(pave(BP / 2, uf, -BL * 0.4, BL * 0.4, n1, b1))      # bride de fixation
        out.append(dict(nom="Broche", label="Broche", cls="haute", mob="z", coul="broche", transp=0,
                        prims=prims))

    e0, e1 = sortie, sortie + P["EcrouHaut"]
    out.append(dict(nom="Ecrou", label="Écrou de pince", cls="basse", mob="z", coul="acier", transp=0,
                    prims=[cyl(P["EcrouDiam"] / 2, e0, e1)]))
    if jauge > e1 + 0.1:
        out.append(dict(nom="PorteOutil", label="Porte-outil", cls="basse", mob="z", coul="acier", transp=0,
                        prims=[cyl(P["PorteOutilDiam"] / 2, e1, jauge)]))
    out.append(dict(nom="Outil", label="Outil", cls="outil", mob="z", coul="outil", transp=0,
                    prims=[cyl(max(rayon, 0.05), 0.0, max(sortie, 0.1))]))

    if P["HotteActive"] >= 0.5:
        h0 = jauge - P["HotteBas"]
        out.append(dict(nom="Hotte", label="Hotte d'aspiration", cls="hotte", mob="z", coul="hotte", transp=60,
                        prims=[cyl(P["HotteDiam"] / 2, h0, h0 + P["HotteHaut"], anneau=4.0)]))
    return out


def forme(prims):
    solides = []
    for k, cx, cy, hx, hy, z0, z1, anneau in prims:
        h = max(z1 - z0, 0.01)
        if k == "box":
            solides.append(Part.makeBox(max(2 * hx, 0.01), max(2 * hy, 0.01), h, App.Vector(cx - hx, cy - hy, z0)))
        else:
            c = Part.makeCylinder(hx, h, App.Vector(cx, cy, z0))
            if 0 < anneau < hx:
                c = c.cut(Part.makeCylinder(hx - anneau, h, App.Vector(cx, cy, z0)))
            solides.append(c)
    return solides[0] if len(solides) == 1 else Part.makeCompound(solides)


def forme_corps(c):
    f = c.get("forme")
    return f if f is not None else forme(c["prims"])


def decalage(mob, x, y, z, axe):
    """Translation d'un corps quand la pointe est en (x, y, z). Accepte scalaires ou tableaux."""
    zero = x * 0
    if mob == "fixe":
        return zero, zero, zero
    if mob == "portique":
        return (x, zero, zero) if axe == 0 else (zero, y, zero)
    if mob == "chariot":
        return x, y, zero
    return x, y, z


def style(obj, c):
    if not App.GuiUp:
        return
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    try:
        vo.ShapeColor = COULEURS[c["coul"]]
        vo.Transparency = int(c["transp"])
    except Exception:
        pass


def table_z(P, job):
    if job is not None and P["TableZAuto"] >= 0.5:
        try:
            return job.Stock.Shape.BoundBox.ZMin
        except Exception:
            pass
    return P["TableZ"]


def groupe_machine(doc, creer=True):
    grp = doc.getObject(NOM_GROUPE)
    if grp is None and creer:
        grp = doc.addObject("App::DocumentObjectGroup", NOM_GROUPE)
        grp.Label = "Machine (CAM Machinist)"
        grp.addProperty("App::PropertyString", "Profil", GROUPE_PROPS, "Profil machine utilisé")
        grp.addProperty("App::PropertyString", "ProfilParams", GROUPE_PROPS,
                        "Copie des cotes du profil, utilisée si le profil manque sur ce poste")
        try:
            grp.setEditorMode("ProfilParams", 2)
        except Exception:
            pass
    return grp


def construire_machine(doc, P, cfg, zt, modele=None):
    """Crée ou met à jour les objets de la machine dans le document."""
    grp = groupe_machine(doc)
    objets = {}
    for c in corps(P, cfg, zt, modele):
        nom = PREFIXE + c["nom"]
        o = doc.getObject(nom)
        if o is None:
            o = doc.addObject("Part::Feature", nom)
            grp.addObject(o)
        o.Label = c["label"]
        o.Shape = forme_corps(c)
        o.Placement = App.Placement()
        style(o, c)
        objets[c["nom"]] = o
    for o in list(grp.Group):
        if o.Name.startswith(PREFIXE) and o.Name[len(PREFIXE):] not in objets:
            doc.removeObject(o.Name)
    if doc.getObject(NOM_BRIDAGE) is None:
        b = doc.addObject("App::DocumentObjectGroup", NOM_BRIDAGE)
        b.Label = "Bridage"
    # machine dessinée par l'ancienne macro Excitech : masquée pour ne pas se superposer
    for ancien in ("Machine_Excitech", "Collisions_Excitech"):
        g = doc.getObject(ancien)
        if g is not None and App.GuiUp:
            try:
                g.ViewObject.Visibility = False
                for o in g.Group:
                    o.ViewObject.Visibility = False
            except Exception:
                pass
    doc.recompute()
    return objets


# =============================================================================
#  Mise en place du Job
# =============================================================================

def lire_mise_en_place(job):
    out = {}
    for prop, cle, defaut, _aide in MISE_EN_PLACE:
        v = getattr(job, prop, None) if job is not None else None
        v = getattr(v, "Value", v)
        try:
            out[cle] = float(v)
        except (TypeError, ValueError):
            out[cle] = float(defaut)
    return out


def ecrire_mise_en_place(job, valeurs):
    for prop, cle, _defaut, aide in MISE_EN_PLACE:
        if cle not in valeurs:
            continue
        if not hasattr(job, prop):
            typ = "App::PropertyBool" if cle == "TableZAuto" else "App::PropertyDistance"
            job.addProperty(typ, prop, GROUPE_PROPS, aide)
        if cle == "TableZAuto":
            setattr(job, prop, bool(valeurs[cle] >= 0.5))
        else:
            setattr(job, prop, float(valeurs[cle]))


def params_complets(P_machine, job):
    P = dict(P_machine)
    P.update(lire_mise_en_place(job))
    return P

# =============================================================================
#  Job, Tool Controllers et parcours
# =============================================================================

def lister_jobs(doc):
    return [o for o in doc.Objects
            if hasattr(o, "Operations") and hasattr(o, "Stock") and hasattr(o, "Model")]


def tc_de(op):
    o = op
    for _ in range(12):
        tc = getattr(o, "ToolController", None)
        if tc is not None:
            return tc
        o = getattr(o, "Base", None)
        if o is None or isinstance(o, (list, tuple)):
            break
    return None


def _valeur(v, defaut=None):
    v = getattr(v, "Value", v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def rayon_outil(tc, P):
    outil = getattr(tc, "Tool", None) if tc is not None else None
    d = _valeur(getattr(outil, "Diameter", None)) if outil is not None else None
    tige = _valeur(getattr(outil, "ShankDiameter", None)) if outil is not None else None
    if d is None or d <= 0:
        d = P["OutilDiam"]
    if tige and tige > d:
        d = tige
    return d / 2


def reglage_tc(tc, P, ajouter=True):
    """Jauge et sortie de l'outil : propriétés du Tool Controller, sinon défauts du tableur."""
    if tc is None:
        return P["Jauge"], P["Sortie"]
    if ajouter:
        for nom, defaut, aide in (("JaugeMachine", P["Jauge"], "Nez de broche jusqu'à la pointe de l'outil"),
                                  ("SortieMachine", P["Sortie"], "Longueur d'outil qui dépasse de l'écrou")):
            if not hasattr(tc, nom):
                try:
                    tc.addProperty("App::PropertyLength", nom, GROUPE_PROPS, aide)
                    setattr(tc, nom, defaut)
                except Exception as e:
                    avert("Impossible d'ajouter %s à %s : %s" % (nom, tc.Label, e))
    j = _valeur(getattr(tc, "JaugeMachine", None), P["Jauge"])
    s = _valeur(getattr(tc, "SortieMachine", None), P["Sortie"])
    return j, s


def code_g(nom):
    nom = nom.strip().upper()
    if not nom.startswith("G"):
        return None
    try:
        return float(nom[1:])
    except ValueError:
        return None


CYCLES = {73.0, 74.0, 76.0, 81.0, 82.0, 83.0, 84.0, 85.0, 86.0, 87.0, 88.0, 89.0}


class Parcours(object):
    """Parcours d'outil découpé en points réguliers, toutes opérations actives du Job."""

    def __init__(self):
        self.X = self.Y = self.Z = None
        self.OP = self.LIGNE = self.CFG = self.RAPIDE = None
        self.ops = []           # dicts : label, outil, cfg
        self.cfgs = []          # (jauge, sortie, rayon)
        self.avertissements = []

    def __len__(self):
        return 0 if self.X is None else len(self.X)


def echantillonner(job, P, ajouter_props=True):
    pas = max(P["PasEchantillon"], 0.5)
    pc = Parcours()
    xs, ys, zs, opi, li_, rap = [], [], [], [], [], []
    try:
        zdepart = job.Stock.Shape.BoundBox.ZMax + 20.0
    except Exception:
        zdepart = 50.0
    cur = None
    g99 = False
    plan = 17
    signale = set()

    def pousser(p, oi, li, rapide):
        xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
        opi.append(oi); li_.append(li); rap.append(rapide)

    def segment(a, b, oi, li, rapide):
        d = math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)
        n = max(1, int(math.ceil(d / pas)))
        for k in range(1, n + 1):
            t = k / float(n)
            pousser((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2])), oi, li, rapide)
        return list(b)

    for op in job.Operations.Group:
        if not getattr(op, "Active", True):
            continue
        chemin = getattr(op, "Path", None)
        if chemin is None or not chemin.Commands:
            continue
        tc = tc_de(op)
        j, s = reglage_tc(tc, P, ajouter_props)
        cfg = (round(j, 3), round(s, 3), round(rayon_outil(tc, P), 3))
        if cfg not in pc.cfgs:
            pc.cfgs.append(cfg)
        oi = len(pc.ops)
        pc.ops.append({"label": op.Label, "outil": tc.Label if tc is not None else "?", "cfg": pc.cfgs.index(cfg)})

        for li, cmd in enumerate(chemin.Commands):
            g = code_g(cmd.Name)
            if g is None:
                continue
            p = cmd.Parameters
            if g in (98.0, 99.0):
                g99 = (g == 99.0)
                continue
            if g in (17.0, 18.0, 19.0):
                plan = int(g)
                continue
            if g == 91.0 and "G91" not in signale:
                signale.add("G91")
                pc.avertissements.append("%s : G91 (incrémental) ignoré, positions fausses possibles." % op.Label)
                continue
            if not (g in (0.0, 1.0, 2.0, 3.0) or g in CYCLES):
                continue

            if cur is None:
                cur = [p.get("X", 0.0), p.get("Y", 0.0), p.get("Z", zdepart)]
                pousser(cur, oi, li, True)
            fin = [p.get("X", cur[0]), p.get("Y", cur[1]), p.get("Z", cur[2])]

            if g in (0.0, 1.0):
                cur = segment(cur, fin, oi, li, g == 0.0)

            elif g in (2.0, 3.0):
                if plan != 17 or ("I" not in p and "J" not in p):
                    if "arc" not in signale:
                        signale.add("arc")
                        pc.avertissements.append("%s : arc hors plan XY ou au rayon R, approché par une droite." % op.Label)
                    cur = segment(cur, fin, oi, li, False)
                    continue
                cx, cy = cur[0] + p.get("I", 0.0), cur[1] + p.get("J", 0.0)
                r = math.hypot(cur[0] - cx, cur[1] - cy)
                a0 = math.atan2(cur[1] - cy, cur[0] - cx)
                a1 = math.atan2(fin[1] - cy, fin[0] - cx)
                if g == 2.0:
                    balayage = a0 - a1
                else:
                    balayage = a1 - a0
                while balayage <= 1e-9:
                    balayage += 2 * math.pi
                sens = -1.0 if g == 2.0 else 1.0
                long_arc = math.hypot(r * balayage, fin[2] - cur[2])
                n = max(1, int(math.ceil(long_arc / pas)))
                z0 = cur[2]
                for k in range(1, n):
                    t = k / float(n)
                    a = a0 + sens * balayage * t
                    pousser((cx + r * math.cos(a), cy + r * math.sin(a), z0 + t * (fin[2] - z0)), oi, li, False)
                pousser(fin, oi, li, False)
                cur = fin

            else:  # cycle de perçage
                R = p.get("R", cur[2])
                zfond = p.get("Z", cur[2])
                xt, yt = p.get("X", cur[0]), p.get("Y", cur[1])
                zinit = cur[2]
                if zinit < R:
                    cur = segment(cur, [cur[0], cur[1], R], oi, li, True)
                    zinit = R
                cur = segment(cur, [xt, yt, zinit], oi, li, True)
                cur = segment(cur, [xt, yt, R], oi, li, True)
                cur = segment(cur, [xt, yt, zfond], oi, li, False)
                cur = segment(cur, [xt, yt, R if g99 else zinit], oi, li, True)

    pc.X = np.array(xs, dtype=np.float64)
    pc.Y = np.array(ys, dtype=np.float64)
    pc.Z = np.array(zs, dtype=np.float64)
    pc.OP = np.array(opi, dtype=np.int32)
    pc.LIGNE = np.array(li_, dtype=np.int32)
    pc.RAPIDE = np.array(rap, dtype=bool)
    cfg_op = np.array([o["cfg"] for o in pc.ops], dtype=np.int32) if pc.ops else np.zeros(0, np.int32)
    pc.CFG = cfg_op[pc.OP] if len(pc.OP) else np.zeros(0, np.int32)
    return pc


# =============================================================================
#  Carte des obstacles (vue de dessus) et contrôle
# =============================================================================

class Grille(object):
    def __init__(self, xmin, ymin, xmax, ymax, res):
        self.res = float(res)
        self.x0, self.y0 = xmin, ymin
        self.nx = int(math.ceil((xmax - xmin) / self.res)) + 1
        self.ny = int(math.ceil((ymax - ymin) / self.res)) + 1

    def vide(self):
        return np.full((self.ny, self.nx), -np.inf, dtype=np.float32)

    def ix(self, x):
        return np.rint((np.asarray(x) - self.x0) / self.res).astype(np.int64)

    def iy(self, y):
        return np.rint((np.asarray(y) - self.y0) / self.res).astype(np.int64)


def rasteriser(G, m, forme_obst, tol=0.5):
    """Hauteur maximale de la forme sur chaque case (z-buffer par triangles)."""
    try:
        pts, tris = forme_obst.tessellate(tol)
    except Exception as e:
        avert("Tessellation impossible : %s" % e)
        return
    if not pts:
        return
    V = np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float64)
    res = G.res
    # sommets (capte les arêtes et parois fines)
    ii, jj = G.ix(V[:, 0]), G.iy(V[:, 1])
    ok = (ii >= 0) & (ii < G.nx) & (jj >= 0) & (jj < G.ny)
    np.maximum.at(m, (jj[ok], ii[ok]), V[ok, 2].astype(np.float32))
    for a, b, c in tris:
        A, B, C = V[a], V[b], V[c]
        det = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
        if abs(det) < 1e-9:
            continue
        i0 = max(int(math.ceil((min(A[0], B[0], C[0]) - G.x0) / res)), 0)
        i1 = min(int(math.floor((max(A[0], B[0], C[0]) - G.x0) / res)), G.nx - 1)
        j0 = max(int(math.ceil((min(A[1], B[1], C[1]) - G.y0) / res)), 0)
        j1 = min(int(math.floor((max(A[1], B[1], C[1]) - G.y0) / res)), G.ny - 1)
        if i1 < i0 or j1 < j0:
            continue
        X, Y = np.meshgrid(G.x0 + np.arange(i0, i1 + 1) * res, G.y0 + np.arange(j0, j1 + 1) * res)
        l1 = ((B[1] - C[1]) * (X - C[0]) + (C[0] - B[0]) * (Y - C[1])) / det
        l2 = ((C[1] - A[1]) * (X - C[0]) + (A[0] - C[0]) * (Y - C[1])) / det
        l3 = 1.0 - l1 - l2
        dedans = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        if not dedans.any():
            continue
        Zt = (l1 * A[2] + l2 * B[2] + l3 * C[2]).astype(np.float32)
        sous = m[j0:j1 + 1, i0:i1 + 1]
        np.maximum(sous, np.where(dedans, Zt, np.float32(-np.inf)), out=sous)


def _glisse_max(a, w, axe):
    def tr(arr, d, f):
        idx = [slice(None)] * arr.ndim
        idx[axe] = slice(d, f)
        return arr[tuple(idx)]
    out, k = a, 1
    while 2 * k <= w:
        n = out.shape[axe]
        out = np.maximum(tr(out, 0, n - k), tr(out, k, n))
        k *= 2
    if k < w:
        r = w - k
        n = out.shape[axe]
        out = np.maximum(tr(out, 0, n - r), tr(out, r, n))
    return out


def dilater_rect(m, hx, hy):
    if hx > 0:
        m = _glisse_max(np.pad(m, ((0, 0), (hx, hx)), constant_values=-np.inf), 2 * hx + 1, 1)
    if hy > 0:
        m = _glisse_max(np.pad(m, ((hy, hy), (0, 0)), constant_values=-np.inf), 2 * hy + 1, 0)
    return m


def dilater_disque(m, rc):
    R = int(math.floor(rc))
    lignes = {}
    out = np.full_like(m, -np.inf)
    ny = m.shape[0]
    for dy in range(-R, R + 1):
        h = int(math.floor(math.sqrt(max(rc * rc - dy * dy, 0.0))))
        if h not in lignes:
            lignes[h] = dilater_rect(m, h, 0)
        rm = lignes[h]
        if dy >= 0:
            out[:ny - dy] = np.maximum(out[:ny - dy], rm[dy:])
        else:
            out[-dy:] = np.maximum(out[-dy:], rm[:ny + dy])
    return out


def formes_bridage(doc):
    g = doc.getObject(NOM_BRIDAGE)
    res = []

    def parcourir(o):
        if o.isDerivedFrom("App::DocumentObjectGroup"):
            for e in o.Group:
                parcourir(e)
            return
        sh = getattr(o, "Shape", None)
        if sh is not None and not sh.isNull():
            res.append(sh)
    if g is not None:
        for e in g.Group:
            parcourir(e)
    return res


def formes_piece(job):
    res = []
    try:
        for o in job.Model.Group:
            sh = getattr(o, "Shape", None)
            if sh is not None and not sh.isNull():
                res.append(sh)
    except Exception:
        pass
    return res


def forme_brut(job):
    try:
        sh = job.Stock.Shape
        return [] if sh.isNull() else [sh]
    except Exception:
        return []


class Resultat(object):
    def __init__(self):
        self.evenements = []     # dicts
        self.touche = {}         # nom de corps -> tableau booléen (surlignage)
        self.infos = []


def solide_prim(pr, dx, dy, dz):
    k, cx, cy, hx, hy, z0, z1, anneau = pr[:8]
    h = max(z1 - z0, 0.01)
    if k == "box":
        return Part.makeBox(max(2 * hx, 0.01), max(2 * hy, 0.01), h, App.Vector(cx + dx - hx, cy + dy - hy, z0 + dz))
    c = Part.makeCylinder(hx, h, App.Vector(cx + dx, cy + dy, z0 + dz))
    if 0 < anneau < hx:
        c = c.cut(Part.makeCylinder(hx - anneau, h, App.Vector(cx + dx, cy + dy, z0 + dz)))
    return c


def distance_exacte(sol, obs):
    """Distance entre deux solides, 0 s'ils se recouvrent (même si l'un contient l'autre)."""
    try:
        d = sol.distToShape(obs)[0]
    except Exception:
        return 0.0
    if d > 1e-6:
        try:
            if obs.isInside(sol.Vertexes[0].Point, 1e-6, True) or sol.isInside(obs.Vertexes[0].Point, 1e-6, True):
                return 0.0
        except Exception:
            pass
    return d


class Budget(object):
    def __init__(self, n):
        self.reste = n
        self.depasse = False


def verifier_exact(pr, dx, dy, dz, obstacles, mg, budget):
    """Reprend les points suspects avec la vraie géométrie. Renvoie (confirmé, distance)."""
    n = len(dx)
    conf = np.ones(n, bool)
    dist = np.zeros(n)
    if not obstacles:
        return conf, dist
    for i in range(n):
        if budget.reste <= 0:
            budget.depasse = True
            break
        sol = solide_prim(pr, float(dx[i]), float(dy[i]), float(dz[i]))
        bb = sol.BoundBox
        bb.enlarge(max(mg, 0.0) + 0.01)
        dmin = np.inf
        for obs, obb in obstacles:
            if not bb.intersect(obb):
                continue
            budget.reste -= 1
            dmin = min(dmin, distance_exacte(sol, obs))
            if dmin <= 1e-6:
                break
        dist[i] = dmin
        conf[i] = (dmin <= 1e-6) if mg <= 0 else (dmin < mg)
    return conf, dist


def controler(doc, job, P, pc, zt, modele=None, progression=None):
    R = Resultat()
    n = len(pc)
    if n == 0:
        R.infos.append("Parcours vide : aucune opération active avec un chemin.")
        return R
    axe = axe_portique(P)
    res = max(P["ResolutionGrille"], 1.0)
    marge = {"marge": P["MargeSecurite"], "plateau": -P["TolerancePlateau"], "zero": 0.0}
    mxy = max(P["MargeSecurite"], 0.0)

    obstacles = {"bridage": formes_bridage(doc), "piece": formes_piece(job), "brut": forme_brut(job)}
    tx0, ty0 = -P["OrigineX"], -P["OrigineY"]
    tx1, ty1 = tx0 + P["TableX"], ty0 + P["TableY"]

    # Étendue de la grille : table, obstacles et tous les centres de primitives
    xmin, ymin, xmax, ymax = tx0, ty0, tx1, ty1
    for lst in obstacles.values():
        for sh in lst:
            bb = sh.BoundBox
            xmin, ymin = min(xmin, bb.XMin), min(ymin, bb.YMin)
            xmax, ymax = max(xmax, bb.XMax), max(ymax, bb.YMax)
    corps_cfg = [corps(P, c, zt, modele) for c in pc.cfgs]
    for lst in corps_cfg:
        for c in lst:
            if c["cls"] is None:
                continue
            dx, dy, _dz = decalage(c["mob"], pc.X, pc.Y, pc.Z, axe)
            for pr in c["prims"]:
                cx, cy = pr[1] + dx, pr[2] + dy
                xmin, xmax = min(xmin, float(np.min(cx))), max(xmax, float(np.max(cx)))
                ymin, ymax = min(ymin, float(np.min(cy))), max(ymax, float(np.max(cy)))
    xmin, ymin, xmax, ymax = xmin - 20, ymin - 20, xmax + 20, ymax + 20
    while ((xmax - xmin) / res) * ((ymax - ymin) / res) > 6e6:
        res *= 1.5
    if res > P["ResolutionGrille"] + 1e-9:
        R.infos.append("Grille élargie à %.1f mm pour rester rapide." % res)
    G = Grille(xmin, ymin, xmax, ymax, res)

    table_solide = Part.makeBox(P["TableX"], P["TableY"], max(P["TableEp"], 0.1),
                                App.Vector(tx0, ty0, zt - max(P["TableEp"], 0.1)))
    exacts = {"table": [table_solide]}
    exacts.update(obstacles)
    exacts = {k: [(s, s.BoundBox) for s in v] for k, v in exacts.items()}
    budget = Budget(int(P.get("BudgetExact", 4000)))

    cartes = {}
    m = G.vide()
    i0, i1 = max(int(math.ceil((tx0 - G.x0) / res)), 0), min(int(math.floor((tx1 - G.x0) / res)), G.nx - 1)
    j0, j1 = max(int(math.ceil((ty0 - G.y0) / res)), 0), min(int(math.floor((ty1 - G.y0) / res)), G.ny - 1)
    m[j0:j1 + 1, i0:i1 + 1] = zt
    cartes["table"] = m
    for cat, lst in obstacles.items():
        if not lst:
            continue
        m = G.vide()
        for sh in lst:
            rasteriser(G, m, sh)
            if progression:
                progression()
        cartes[cat] = m
    hauts = {k: float(np.max(v)) for k, v in cartes.items()}

    # Contrôle vectorisé
    cache = {}

    def carte_dilatee(cat, pr):
        k, _cx, _cy, hx, hy = pr[:5]
        if k == "box":
            cle = (cat, "b", int(math.ceil((hx + mxy) / res)) + 1, int(math.ceil((hy + mxy) / res)) + 1)
            if cle not in cache:
                cache[cle] = dilater_rect(cartes[cat], cle[2], cle[3])
        else:
            rc = round((hx + mxy) / res + 1.0, 2)
            cle = (cat, "d", rc)
            if cle not in cache:
                cache[cle] = dilater_disque(cartes[cat], rc)
        return cache[cle]

    marques = {}   # (label corps, cat, gravité) -> [hit, garde]
    jauges = np.array([c[0] for c in pc.cfgs])[pc.CFG]
    for ci, lst in enumerate(corps_cfg):
        sel = np.flatnonzero(pc.CFG == ci)
        if sel.size == 0:
            continue
        X, Y, Z = pc.X[sel], pc.Y[sel], pc.Z[sel]
        for c in lst:
            if c["cls"] is None:
                continue
            dx, dy, dz = decalage(c["mob"], X, Y, Z, axe)
            for cls, cat, grav, mk in REGLES:
                if cls != c["cls"] or cat not in cartes:
                    continue
                mg = marge[mk]
                cle = (c["label"], cat, grav)
                if cle not in marques:
                    marques[cle] = [np.zeros(n, bool), np.full(n, np.inf), c["nom"]]
                hit, garde = marques[cle][0], marques[cle][1]
                for pr in c["prims"]:
                    bas = pr[5] + dz
                    if float(np.min(bas)) >= hauts[cat] + mg:
                        continue
                    dil = carte_dilatee(cat, pr)
                    ii = np.clip(G.ix(pr[1] + dx), 0, G.nx - 1)
                    jj = np.clip(G.iy(pr[2] + dy), 0, G.ny - 1)
                    g = (bas - dil[jj, ii]).astype(np.float64)
                    touche = g < mg
                    cand = np.flatnonzero(touche)
                    if cand.size and mk != "plateau":
                        conf, dist = verifier_exact(pr, dx[cand], dy[cand], dz[cand], exacts.get(cat, []), mg, budget)
                        touche[cand] = conf
                        # frôlement : distance réelle ; recouvrement : pénétration verticale
                        g_c = np.where(dist > 1e-6, dist, np.minimum(g[cand], 0.0))
                        g_c[~conf] = np.inf
                        g[cand] = g_c
                    hit[sel] |= touche
                    garde[sel] = np.minimum(garde[sel], g)
                    if progression:
                        progression()
        if progression:
            progression()
    if budget.depasse:
        R.infos.append("Vérification fine plafonnée : certains points restent signalés par la grille seule (prudent).")

    # Les points « sous le brut » déjà en collision avec la pièce ne sont pas doublés
    for (lab, cat, grav), v in list(marques.items()):
        if cat == "brut" and grav == "À VÉRIFIER":
            autre = marques.get((lab, "piece", "COLLISION"))
            if autre is not None:
                v[0] &= ~autre[0]

    groupes = {}

    def ajouter_runs(hit, garde, grav, corps_label, obstacle, nom_corps):
        """Regroupe les passages successifs d'un même problème dans une même opération."""
        idx = np.flatnonzero(hit)
        if idx.size == 0:
            return
        coupe = np.flatnonzero(np.diff(idx) > 1)
        debuts = np.r_[idx[0], idx[coupe + 1]]
        fins = np.r_[idx[coupe], idx[-1]]
        for d, f in zip(debuts, fins):
            k = int(d + int(np.argmin(garde[d:f + 1])))
            cle = (grav, corps_label, obstacle, int(pc.OP[d]))
            e = groupes.get(cle)
            if e is None:
                e = {"gravite": grav, "corps": corps_label, "obstacle": obstacle, "debut": int(d),
                     "pire": k, "garde": float(garde[k]), "nom_corps": nom_corps, "passages": 0}
                groupes[cle] = e
                R.evenements.append(e)
            e["passages"] += 1
            if garde[k] < e["garde"]:
                e["garde"], e["pire"] = float(garde[k]), k

    for (lab, cat, grav), (hit, garde, nom_c) in marques.items():
        ajouter_runs(hit, garde, grav, lab, NOMS_OBSTACLES[cat], nom_c)
        if nom_c in R.touche:
            R.touche[nom_c] |= hit
        else:
            R.touche[nom_c] = hit.copy()

    # Courses
    lim = [("X", pc.X, P["CourseXmin"] - P["OrigineX"], P["CourseXmax"] - P["OrigineX"]),
           ("Y", pc.Y, P["CourseYmin"] - P["OrigineY"], P["CourseYmax"] - P["OrigineY"]),
           ("Z (nez de broche)", pc.Z + jauges, zt + P["NezHautMax"] - P["CourseZ"], zt + P["NezHautMax"])]
    for nom, v, vmin, vmax in lim:
        g = np.minimum(v - vmin, vmax - v)
        ajouter_runs(g < 0, g, "COURSE", "Course " + nom, "limite", None)

    # jamais de contact, seulement la garde demandée non respectée
    for e in R.evenements:
        if e["gravite"] == "COLLISION" and e["garde"] > 0:
            e["gravite"] = "FRÔLEMENT"
    R.evenements.sort(key=lambda e: (GRAVITES.index(e["gravite"]), e["debut"]))
    R.infos.append("%d points contrôlés, pas %.1f mm, grille %.1f mm." % (n, P["PasEchantillon"], res))
    R.infos.append("Obstacles : table, %d bridage(s), %d pièce(s), brut %s."
                   % (len(obstacles["bridage"]), len(obstacles["piece"]), "oui" if obstacles["brut"] else "non"))
    return R


def texte_evenement(e, pc, deux_lignes=False):
    k = e["pire"]
    op = pc.ops[int(pc.OP[k])]["label"] if len(pc.ops) else "?"
    if e["obstacle"] == "limite":
        quoi = "%s dépassée de %.1f mm" % (e["corps"], -e["garde"])
    else:
        quoi = "%s ↔ %s, garde mini %.1f mm" % (e["corps"], e["obstacle"], e["garde"])
    n = e.get("passages", 1)
    if deux_lignes:
        tete, _sep, garde = quoi.partition(", ")
        return "%s · %s\n      %s%s · %s%s · X %.1f Y %.1f Z %.1f" % (
            e["gravite"], tete, garde + " · " if garde else "", op,
            "%d passages" % n if n > 1 else "commande %d" % int(pc.LIGNE[k]), "",
            pc.X[k], pc.Y[k], pc.Z[k])
    return "%s · %s · %s%s · pire en X %.1f Y %.1f Z %.1f (commande %d)" % (
        e["gravite"], quoi, op, (" · %d passages" % n) if n > 1 else "",
        pc.X[k], pc.Y[k], pc.Z[k], int(pc.LIGNE[k]))


def rapport(R, pc, job):
    lignes = ["CAM Machinist · contrôle du Job « %s »" % job.Label]
    lignes += R.infos
    lignes += pc.avertissements
    if not R.evenements:
        lignes.append("Aucune collision ni dépassement de course détecté avec ces cotes.")
    else:
        compte = {}
        for e in R.evenements:
            compte[e["gravite"]] = compte.get(e["gravite"], 0) + 1
        lignes.append(" · ".join("%s : %d" % (g, compte[g]) for g in GRAVITES if g in compte))
        lignes += [texte_evenement(e, pc) for e in R.evenements]
    return "\n".join(lignes)


def marquer(doc, R, pc, maxi=200):
    g = doc.getObject(NOM_COLLISIONS)
    if g is not None:
        for o in list(g.Group):
            doc.removeObject(o.Name)
    if not R.evenements:
        if g is not None:
            doc.removeObject(g.Name)
        doc.recompute()
        return
    if g is None:
        g = doc.addObject("App::DocumentObjectGroup", NOM_COLLISIONS)
    g.Label = "Collisions (CAM Machinist)"
    couleurs = {"COLLISION": (0.9, 0.0, 0.0), "COURSE": (0.6, 0.0, 0.8), "FRÔLEMENT": (1.0, 0.4, 0.0),
                "À VÉRIFIER": (1.0, 0.6, 0.0), "BROSSE": (1.0, 0.9, 0.0)}
    for i, e in enumerate(R.evenements[:maxi]):
        k = e["pire"]
        o = doc.addObject("Part::Feature", "CMachCol%03d" % i)
        o.Shape = Part.makeSphere(6, App.Vector(pc.X[k], pc.Y[k], pc.Z[k]))
        o.Label = "%s %s" % (e["gravite"].capitalize(), e["corps"])
        g.addObject(o)
        if App.GuiUp:
            try:
                o.ViewObject.ShapeColor = couleurs.get(e["gravite"], (1, 0, 0))
            except Exception:
                pass
    doc.recompute()




# =============================================================================
#  Mesure exacte à une position (modèle STEP compris)
# =============================================================================

def obstacles_exacts(doc, job, P, zt):
    ep = max(P["TableEp"], 0.1)
    table = Part.makeBox(P["TableX"], P["TableY"], ep, App.Vector(-P["OrigineX"], -P["OrigineY"], zt - ep))
    return {"table": [table], "bridage": formes_bridage(doc), "piece": formes_piece(job), "brut": forme_brut(job)}


def mesurer(doc, job, P, pc, i, zt, modele=None, portee=80.0):
    """Distances exactes entre la tête et les obstacles quand la pointe est au point i du parcours.
    Renvoie une liste triée de (distance, corps, obstacle, gravité)."""
    axe = axe_portique(P)
    x, y, z = float(pc.X[i]), float(pc.Y[i]), float(pc.Z[i])
    cfg = pc.cfgs[int(pc.CFG[i])]
    obs = obstacles_exacts(doc, job, P, zt)
    meilleur = {}
    for c in corps(P, cfg, zt, modele):
        if c["cls"] is None:
            continue
        dx, dy, dz = decalage(c["mob"], x, y, z, axe)
        f = forme_corps(c).copy()
        f.translate(App.Vector(dx, dy, dz))
        zone = App.BoundBox(f.BoundBox)
        zone.enlarge(portee)
        for cls, cat, grav, _mk in REGLES:
            if cls != c["cls"]:
                continue
            for sh in obs.get(cat, []):
                if not zone.intersect(sh.BoundBox):
                    continue
                d = distance_exacte(f, sh)
                cle = (c["label"], cat)
                if cle not in meilleur or d < meilleur[cle][0]:
                    meilleur[cle] = (d, c["label"], NOMS_OBSTACLES[cat], grav)
    return sorted(meilleur.values(), key=lambda t: t[0])
