# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# Portique CAM · FabLab Le Boc@l, Centre Social et Socioculturel du Chemillois
"""Panneau latéral : profil machine, mise en place du Job, suivi du parcours, contrôle."""

import json

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import moteur as M
from . import profils

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    from PySide import QtCore
    from PySide import QtGui as QtWidgets

NOM_DOCK = "PortiqueCAMDock"


def ouvrir():
    mw = Gui.getMainWindow()
    d = mw.findChild(QtWidgets.QDockWidget, NOM_DOCK)
    if d is None:
        d = Panneau()
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, d)
    else:
        d.rafraichir()
    d.show()
    d.raise_()
    return d


def instance():
    return Gui.getMainWindow().findChild(QtWidgets.QDockWidget, NOM_DOCK)


def _spin(mini, maxi, val, suffixe=" mm"):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(mini, maxi)
    s.setDecimals(1)
    s.setValue(val)
    s.setSuffix(suffixe)
    s.setKeyboardTracking(False)
    return s


class Panneau(QtWidgets.QDockWidget):
    def __init__(self):
        super(Panneau, self).__init__("Portique CAM")
        self.setObjectName(NOM_DOCK)
        self.doc = None
        self.prof = None
        self.modele = None
        self.P = None
        self.pc = None
        self.res = None
        self.zt = 0.0
        self.objets = {}
        self.mob = {}
        self.formes_cfg = {}
        self.ci_affiche = None
        self.surligne = set()
        self._maj = False

        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        l0 = QtWidgets.QHBoxLayout()
        l0.addWidget(QtWidgets.QLabel("Machine :"))
        self.cb_profil = QtWidgets.QComboBox()
        self.cb_profil.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_profil.setMinimumContentsLength(8)
        self.cb_profil.currentIndexChanged.connect(self.profil_choisi)
        l0.addWidget(self.cb_profil, 1)
        b = QtWidgets.QPushButton("Modifier…")
        b.setToolTip("Cotes de la machine, modèle STEP de la broche, partage du profil")
        b.clicked.connect(self.editer)
        l0.addWidget(b)
        lay.addLayout(l0)

        l1 = QtWidgets.QHBoxLayout()
        l1.addWidget(QtWidgets.QLabel("Job :"))
        self.cb_job = QtWidgets.QComboBox()
        self.cb_job.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_job.setMinimumContentsLength(8)
        self.cb_job.currentIndexChanged.connect(self.job_choisi)
        l1.addWidget(self.cb_job, 1)
        b = QtWidgets.QPushButton("↻")
        b.setMaximumWidth(32)
        b.setToolTip("Relister les profils et les Jobs")
        b.clicked.connect(self.rafraichir)
        l1.addWidget(b)
        lay.addLayout(l1)

        gb = QtWidgets.QGroupBox("Mise en place (depuis le coin de table)")
        fl = QtWidgets.QFormLayout(gb)
        self.sp_ox = _spin(-10000, 10000, 20)
        self.sp_oy = _spin(-10000, 10000, 20)
        self.sp_ox.setToolTip("Position du X0 du Job depuis le coin de table (X0 machine)")
        self.sp_oy.setToolTip("Position du Y0 du Job depuis le coin de table (Y0 machine)")
        fl.addRow("Origine X", self.sp_ox)
        fl.addRow("Origine Y", self.sp_oy)
        self.ck_table = QtWidgets.QCheckBox("Table sous le brut")
        self.ck_table.setToolTip("Le dessus de la table est pris au bas du brut du Job")
        self.ck_table.setChecked(True)
        self.sp_tz = _spin(-2000, 2000, 0)
        self.sp_tz.setEnabled(False)
        fl.addRow(self.ck_table)
        fl.addRow("Sinon, Z table", self.sp_tz)
        for sp in (self.sp_ox, self.sp_oy, self.sp_tz):
            sp.valueChanged.connect(self.mise_en_place_modifiee)
        self.ck_table.toggled.connect(self.mise_en_place_modifiee)
        lay.addWidget(gb)

        self.b_machine = QtWidgets.QPushButton("Dessiner la machine")
        self.b_machine.clicked.connect(self.machine)
        lay.addWidget(self.b_machine)

        self.b_charger = QtWidgets.QPushButton("Charger le parcours du Job")
        self.b_charger.clicked.connect(self.charger)
        lay.addWidget(self.b_charger)

        self.info = QtWidgets.QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        self.curseur = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.curseur.setEnabled(False)
        self.curseur.valueChanged.connect(self.aller)
        lay.addWidget(self.curseur)

        self.pos = QtWidgets.QLabel("")
        self.pos.setWordWrap(True)
        lay.addWidget(self.pos)

        l2 = QtWidgets.QHBoxLayout()
        self.b_lecture = QtWidgets.QPushButton("▶ Lecture")
        self.b_lecture.setEnabled(False)
        self.b_lecture.clicked.connect(self.lecture)
        l2.addWidget(self.b_lecture)
        l2.addWidget(QtWidgets.QLabel("Vitesse"))
        self.vitesse = QtWidgets.QSpinBox()
        self.vitesse.setRange(1, 2000)
        self.vitesse.setValue(10)
        self.vitesse.setToolTip("Points avancés à chaque image")
        l2.addWidget(self.vitesse)
        lay.addLayout(l2)

        l3 = QtWidgets.QHBoxLayout()
        self.b_ctrl = QtWidgets.QPushButton("Contrôler tout le parcours")
        self.b_ctrl.setToolTip("Collisions et courses sur tout le programme")
        self.b_ctrl.setEnabled(False)
        self.b_ctrl.clicked.connect(self.controle)
        l3.addWidget(self.b_ctrl)
        self.b_mesure = QtWidgets.QPushButton("Mesurer ici")
        self.b_mesure.setToolTip("Distances exactes à la position du curseur, avec le vrai modèle STEP de la broche")
        self.b_mesure.setEnabled(False)
        self.b_mesure.clicked.connect(self.mesurer)
        l3.addWidget(self.b_mesure)
        lay.addLayout(l3)

        self.resume = QtWidgets.QLabel("")
        self.resume.setWordWrap(True)
        lay.addWidget(self.resume)

        self.liste = QtWidgets.QListWidget()
        self.liste.setMinimumHeight(140)
        self.liste.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.liste.itemClicked.connect(self.choisir)
        lay.addWidget(self.liste, 1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(w)
        scroll.setMinimumWidth(w.minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 4)
        self.setWidget(scroll)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.pas)
        self.rafraichir()

    # ------------------------------------------------------------------ état
    def job(self):
        if self.doc is None or self.cb_job.currentIndex() < 0:
            return None
        return self.doc.getObject(self.cb_job.itemData(self.cb_job.currentIndex()))

    def ident(self):
        i = self.cb_profil.currentIndex()
        return self.cb_profil.itemData(i) if i >= 0 else None

    def arreter(self):
        self.timer.stop()
        self.b_lecture.setText("▶ Lecture")

    def occupe(self, oui):
        if oui:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def oublier_parcours(self):
        self.arreter()
        self.pc = None
        self.res = None
        self.formes_cfg = {}
        self.ci_affiche = None
        self.surligne = set()
        self.liste.clear()
        self.resume.setText("")
        self.pos.setText("")
        for b in (self.curseur, self.b_lecture, self.b_ctrl, self.b_mesure):
            b.setEnabled(False)

    def rafraichir(self, choisir=None):
        self._maj = True
        try:
            doc = App.ActiveDocument
            if doc is not self.doc:
                self.doc = doc
                self.objets, self.mob = {}, {}
                self.oublier_parcours()
            grp = M.groupe_machine(doc, creer=False) if doc else None
            voulu = choisir or (grp.Profil if grp is not None and getattr(grp, "Profil", "") else None) or self.ident()
            self.cb_profil.clear()
            tous = profils.lister()
            for ident, info in sorted(tous.items(), key=lambda kv: kv[1]["nom"].lower()):
                self.cb_profil.addItem(info["nom"] + ("" if not info["fourni"] else " (fourni)"), ident)
            if voulu and grp is not None and voulu not in tous:
                self.cb_profil.addItem("%s (absent de ce poste : cotes du document)" % voulu, voulu)
            i = self.cb_profil.findData(voulu) if voulu else -1
            self.cb_profil.setCurrentIndex(i if i >= 0 else 0)

            ancien = self.cb_job.itemData(self.cb_job.currentIndex()) if self.cb_job.currentIndex() >= 0 else None
            self.cb_job.clear()
            if doc is not None:
                for j in M.lister_jobs(doc):
                    self.cb_job.addItem(j.Label, j.Name)
                k = self.cb_job.findData(ancien) if ancien else -1
                if k >= 0:
                    self.cb_job.setCurrentIndex(k)
        finally:
            self._maj = False
        self.charger_profil()
        self.lire_mise_en_place()
        if doc is None:
            self.info.setText("Ouvrir d'abord un document avec un Job CAM.")
        elif self.cb_job.count() == 0:
            self.info.setText("Pas de Job CAM dans ce document : la machine peut quand même être dessinée.")

    def charger_profil(self):
        ident = self.ident()
        self.cb_profil.setToolTip(self.cb_profil.currentText())
        self.prof, self.modele = None, None
        if ident:
            self.prof = profils.charger(ident)
        if self.prof is None:
            grp = M.groupe_machine(self.doc, creer=False) if self.doc else None
            instant = getattr(grp, "ProfilParams", "") if grp is not None else ""
            p = None
            if instant:
                try:
                    p = json.loads(instant)
                except ValueError:
                    p = None
            self.prof = profils.nouveau(ident or "Machine")
            if p:
                self.prof["params"] = M.completer_params(p)
                M.avert("Profil « %s » absent de ce poste : cotes enregistrées dans le document utilisées." % ident)
        else:
            try:
                self.modele = profils.modele(self.prof)
            except Exception as e:
                M.avert("Modèle de broche illisible : %s" % e)
                self.modele = None

    def lire(self):
        j = self.job()
        self.P = M.params_complets(self.prof["params"], j)
        self.zt = M.table_z(self.P, j)
        return self.P

    def lire_mise_en_place(self):
        mp = M.lire_mise_en_place(self.job())
        self._maj = True
        try:
            self.sp_ox.setValue(mp["OrigineX"])
            self.sp_oy.setValue(mp["OrigineY"])
            self.ck_table.setChecked(mp["TableZAuto"] >= 0.5)
            self.sp_tz.setValue(mp["TableZ"])
            self.sp_tz.setEnabled(mp["TableZAuto"] < 0.5)
        finally:
            self._maj = False

    # --------------------------------------------------------------- actions
    def profil_choisi(self, _i):
        if self._maj:
            return
        self.charger_profil()
        self.formes_cfg = {}
        self.ci_affiche = None
        self.res = None
        self.liste.clear()
        self.resume.setText("")
        if self.doc is not None and M.groupe_machine(self.doc, creer=False) is not None:
            self.machine()

    def job_choisi(self, _i):
        if self._maj:
            return
        self.oublier_parcours()
        self.lire_mise_en_place()

    def mise_en_place_modifiee(self, *_a):
        self.sp_tz.setEnabled(not self.ck_table.isChecked())
        if self._maj:
            return
        j = self.job()
        if j is None:
            return
        M.ecrire_mise_en_place(j, {"OrigineX": self.sp_ox.value(), "OrigineY": self.sp_oy.value(),
                                   "TableZAuto": 1.0 if self.ck_table.isChecked() else 0.0,
                                   "TableZ": self.sp_tz.value()})
        self.res = None
        self.liste.clear()
        self.resume.setText("")
        if self.objets:
            self.machine()

    def editer(self):
        from . import editeur
        editeur.ouvrir(self.ident(), self.doc, rappel=self.profil_enregistre)

    def profil_enregistre(self, ident):
        self.rafraichir(choisir=ident)
        if self.doc is not None and M.groupe_machine(self.doc, creer=False) is not None:
            self.formes_cfg = {}
            self.ci_affiche = None
            self.machine()

    def machine(self):
        if self.doc is None:
            self.rafraichir()
            if self.doc is None:
                return
        self.arreter()
        P = self.lire()
        cfg = (P["Jauge"], P["Sortie"], P["OutilDiam"] / 2)
        self.occupe(True)
        try:
            self.objets = M.construire_machine(self.doc, P, cfg, self.zt, self.modele)
        finally:
            self.occupe(False)
        grp = M.groupe_machine(self.doc)
        grp.Profil = self.ident() or ""
        grp.ProfilParams = json.dumps(self.prof["params"])
        self.mob = {c["nom"]: c["mob"] for c in M.corps(P, cfg, self.zt, self.modele)}
        self.formes_cfg = {}
        self.ci_affiche = None
        self.surligne = set()
        msgs = M.verifier_params(P, self.modele)
        broche = "modèle STEP" if self.modele is not None else "dessinée à partir des cotes"
        self.info.setText("Machine « %s » dessinée, broche %s, dessus de table à Z %.1f."
                          % (self.prof["nom"], broche, self.zt) + ("\n" + "\n".join(msgs) if msgs else ""))
        if self.pc is not None and len(self.pc):
            self.aller(self.curseur.value())
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass

    def charger(self):
        j = self.job()
        if j is None:
            self.info.setText("Choisir un Job.")
            return
        self.arreter()
        self.occupe(True)
        try:
            P = self.lire()
            self.doc.recompute()
            self.pc = M.echantillonner(j, P, True)
            if not self.objets or any(self.doc.getObject(M.PREFIXE + n) is None for n in self.mob):
                self.occupe(False)
                self.machine()
                self.occupe(True)
            self.formes_cfg = {}
            self.ci_affiche = None
            self.res = None
            self.liste.clear()
            self.resume.setText("")
        finally:
            self.occupe(False)
        n = len(self.pc)
        outils = sorted(set(o["outil"] for o in self.pc.ops))
        self.info.setText("%d opération(s), %d point(s), outil(s) : %s.\nJauge et sortie se règlent dans les "
                          "propriétés des Tool Controllers (groupe %s)."
                          % (len(self.pc.ops), n, ", ".join(outils) if outils else "aucun", M.GROUPE_PROPS))
        for a in self.pc.avertissements:
            M.avert(a)
        for b in (self.curseur, self.b_lecture, self.b_ctrl, self.b_mesure):
            b.setEnabled(n > 0)
        self.curseur.setRange(0, max(n - 1, 0))
        self.curseur.setValue(0)
        if n:
            self.aller(0)

    def appliquer_cfg(self, ci):
        if ci not in self.formes_cfg:
            self.formes_cfg[ci] = {c["nom"]: (M.forme_corps(c), c)
                                   for c in M.corps(self.P, self.pc.cfgs[ci], self.zt, self.modele) if c["mob"] == "z"}
        formes = self.formes_cfg[ci]
        grp = M.groupe_machine(self.doc)
        for nom, (f, c) in formes.items():
            o = self.objets.get(nom) or self.doc.getObject(M.PREFIXE + nom)
            if o is None:
                o = self.doc.addObject("Part::Feature", M.PREFIXE + nom)
                o.Label = c["label"]
                grp.addObject(o)
                M.style(o, c)
            self.objets[nom] = o
            self.mob[nom] = "z"
            o.Shape = f
        for nom, mob in self.mob.items():
            if mob == "z" and nom not in formes and self.objets.get(nom) is not None:
                self.objets[nom].Shape = Part.Shape()
        self.ci_affiche = ci

    def aller(self, i):
        if self.pc is None or i >= len(self.pc) or self.P is None:
            return
        x, y, z = float(self.pc.X[i]), float(self.pc.Y[i]), float(self.pc.Z[i])
        ci = int(self.pc.CFG[i])
        if ci != self.ci_affiche:
            self.appliquer_cfg(ci)
        axe = M.axe_portique(self.P)
        for nom, mob in self.mob.items():
            o = self.objets.get(nom)
            if o is None:
                continue
            dx, dy, dz = M.decalage(mob, x, y, z, axe)
            o.Placement = App.Placement(App.Vector(dx, dy, dz), App.Rotation())
        op = self.pc.ops[int(self.pc.OP[i])]
        self.pos.setText("%s · %s · commande %d\nX %.2f   Y %.2f   Z %.2f%s"
                         % (op["label"], op["outil"], int(self.pc.LIGNE[i]), x, y, z,
                            "   (rapide)" if self.pc.RAPIDE[i] else ""))
        if self.res is not None:
            maintenant = set(n for n, h in self.res.touche.items() if h[i])
            if maintenant != self.surligne:
                couleurs = {c["nom"]: c["coul"] for c in M.corps(self.P, self.pc.cfgs[ci], self.zt, self.modele)}
                for n in self.surligne | maintenant:
                    o = self.objets.get(n)
                    if o is None or n not in couleurs:
                        continue
                    try:
                        o.ViewObject.ShapeColor = M.COULEURS["alerte"] if n in maintenant else M.COULEURS[couleurs[n]]
                    except Exception:
                        pass
                self.surligne = maintenant

    def lecture(self):
        if self.timer.isActive():
            self.arreter()
        else:
            if self.curseur.value() >= self.curseur.maximum():
                self.curseur.setValue(0)
            self.timer.start()
            self.b_lecture.setText("⏸ Pause")

    def pas(self):
        v = self.curseur.value() + self.vitesse.value()
        if v >= self.curseur.maximum():
            v = self.curseur.maximum()
            self.arreter()
        self.curseur.setValue(v)

    def controle(self):
        j = self.job()
        if j is None or self.pc is None:
            return
        self.arreter()
        self.lire()
        self.occupe(True)
        try:
            self.res = M.controler(self.doc, j, self.P, self.pc, self.zt, self.modele,
                                   progression=QtWidgets.QApplication.processEvents)
            M.marquer(self.doc, self.res, self.pc)
        finally:
            self.occupe(False)
        App.Console.PrintMessage(M.rapport(self.res, self.pc, j) + "\n")
        self.liste.clear()
        for e in self.res.evenements:
            it = QtWidgets.QListWidgetItem(M.texte_evenement(e, self.pc, deux_lignes=True))
            it.setToolTip(M.texte_evenement(e, self.pc))
            it.setData(QtCore.Qt.UserRole, e["pire"])
            self.liste.addItem(it)
        ev = self.res.evenements
        note = ""
        if self.modele is not None:
            note = "\nBroche STEP contrôlée par son enveloppe (un peu plus grosse que le modèle) : « Mesurer ici » donne la distance exacte."
        if not ev:
            self.resume.setText("Aucun problème détecté avec ces cotes.\n" + "\n".join(self.res.infos) + note)
        else:
            compte = {}
            for e in ev:
                compte[e["gravite"]] = compte.get(e["gravite"], 0) + 1
            self.resume.setText(" · ".join("%s : %d" % (g, compte[g]) for g in M.GRAVITES if g in compte)
                                + "\nCliquer une ligne pour y amener la machine." + note)
        self.surligne = set()
        self.aller(self.curseur.value())

    def mesurer(self):
        j = self.job()
        if j is None or self.pc is None:
            return
        self.arreter()
        self.lire()
        i = self.curseur.value()
        self.occupe(True)
        try:
            res = M.mesurer(self.doc, j, self.P, self.pc, i, self.zt, self.modele)
        finally:
            self.occupe(False)
        if not res:
            txt = "Mesure exacte : aucun obstacle à moins de 80 mm de la tête à cette position."
        else:
            lignes = []
            for d, corps_, obst, grav in res[:6]:
                etat = "CONTACT" if d <= 1e-6 else ("%.1f mm" % d)
                lignes.append("%s ↔ %s : %s" % (corps_, obst, etat))
            txt = "Mesure exacte à cette position :\n" + "\n".join(lignes)
        self.resume.setText(txt)
        App.Console.PrintMessage("[Portique CAM] " + txt.replace("\n", "\n   ") + "\n")

    def choisir(self, it):
        k = it.data(QtCore.Qt.UserRole)
        if k is not None:
            self.arreter()
            self.curseur.setValue(int(k))

    def closeEvent(self, ev):
        self.arreter()
        super(Panneau, self).closeEvent(ev)
