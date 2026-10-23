# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# CAM Machinist · FabLab Le Boc@l, Centre Social et Socioculturel du Chemillois
"""Éditeur de profil machine : cotes, modèle STEP de la broche, partage."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import moteur as M
from . import profils

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide import QtCore, QtGui
    QtWidgets = QtGui

NOM_DOC_ALIGNEMENT = "CAMMachinist_Alignement"
_OUVERT = []


def ouvrir(ident, doc, rappel=None):
    for d in list(_OUVERT):
        try:
            d.raise_()
            d.activateWindow()
            return d
        except RuntimeError:
            _OUVERT.remove(d)
    d = Editeur(ident, doc, rappel)
    _OUVERT.append(d)
    d.show()
    return d


def _nombre(txt):
    return float(str(txt).strip().replace(",", ".").replace(" ", ""))


class Editeur(QtWidgets.QDialog):
    def __init__(self, ident, doc, rappel):
        super(Editeur, self).__init__(Gui.getMainWindow())
        self.setWindowTitle("CAM Machinist · profil machine")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.resize(820, 860)
        self.doc_cam = doc
        self.rappel = rappel
        self.prof = (profils.charger(ident) if ident else None) or profils.nouveau()
        self.modele_en_attente = None
        self.session = None
        self.modifie = False
        self.lignes = {}          # alias -> ligne du tableau
        self._remplissage = False

        lay = QtWidgets.QVBoxLayout(self)

        fl = QtWidgets.QFormLayout()
        self.ed_nom = QtWidgets.QLineEdit()
        self.ed_desc = QtWidgets.QLineEdit()
        self.ed_nom.textEdited.connect(self.marquer_modifie)
        self.ed_desc.textEdited.connect(self.marquer_modifie)
        fl.addRow("Nom de la machine", self.ed_nom)
        fl.addRow("Description", self.ed_desc)
        lay.addLayout(fl)
        self.lbl_origine = QtWidgets.QLabel("")
        self.lbl_origine.setWordWrap(True)
        lay.addWidget(self.lbl_origine)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Paramètre", "Valeur", "Unité", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.cellule_modifiee)
        lay.addWidget(self.table, 1)

        # ---------------------------------------------------- modèle de broche
        gb = QtWidgets.QGroupBox("Modèle 3D de la broche (STEP)")
        gl = QtWidgets.QVBoxLayout(gb)
        self.lbl_modele = QtWidgets.QLabel("")
        self.lbl_modele.setWordWrap(True)
        gl.addWidget(self.lbl_modele)
        r = QtWidgets.QHBoxLayout()
        self.b_import = QtWidgets.QPushButton("Importer un fichier STEP…")
        self.b_import.clicked.connect(self.importer_step)
        self.b_realigner = QtWidgets.QPushButton("Réaligner")
        self.b_realigner.clicked.connect(self.realigner)
        self.b_retirer = QtWidgets.QPushButton("Retirer le modèle")
        self.b_retirer.clicked.connect(self.retirer_modele)
        for b in (self.b_import, self.b_realigner, self.b_retirer):
            r.addWidget(b)
        r.addStretch(1)
        gl.addLayout(r)

        self.cadre = QtWidgets.QFrame()
        cl = QtWidgets.QVBoxLayout(self.cadre)
        cl.setContentsMargins(0, 6, 0, 0)
        self.lbl_etape = QtWidgets.QLabel("")
        self.lbl_etape.setWordWrap(True)
        self.lbl_etape.setStyleSheet("QLabel { background: #fbe9e7; border-left: 4px solid #B71C1C; padding: 6px; }")
        cl.addWidget(self.lbl_etape)
        r = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Aligner sur la sélection")
        b.setToolTip("Le bord circulaire (ou la face plane) choisi devient le nez de broche")
        b.clicked.connect(self.aligner)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Tourner de")
        b.setToolTip("Rotation autour de l'axe de la broche")
        self.sp_angle = QtWidgets.QDoubleSpinBox()
        self.sp_angle.setRange(-360, 360)
        self.sp_angle.setDecimals(1)
        self.sp_angle.setValue(90)
        self.sp_angle.setSuffix(" °")
        b.clicked.connect(lambda: self.transformer(profils.tourner, self.sp_angle.value()))
        r.addWidget(b)
        r.addWidget(self.sp_angle)
        b = QtWidgets.QPushButton("Retourner")
        b.setToolTip("Inverse le sens de l'axe (si la broche pointe vers le haut)")
        b.clicked.connect(lambda: self.transformer(profils.retourner))
        r.addWidget(b)
        r.addStretch(1)
        cl.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        r.addWidget(QtWidgets.QLabel("Décaler le nez de"))
        self.sp_dz = QtWidgets.QDoubleSpinBox()
        self.sp_dz.setRange(-500, 500)
        self.sp_dz.setDecimals(2)
        self.sp_dz.setSuffix(" mm")
        r.addWidget(self.sp_dz)
        b = QtWidgets.QPushButton("Appliquer")
        b.setToolTip("Valeur positive : le modèle monte (le nez réel est plus bas que l'arête choisie)")
        b.clicked.connect(lambda: self.transformer(profils.decaler_z, self.sp_dz.value()))
        r.addWidget(b)
        r.addStretch(1)
        cl.addLayout(r)
        self.ck_coulisse = QtWidgets.QCheckBox("Le modèle comprend aussi la coulisse Z (ne plus la dessiner)")
        self.ck_couper = QtWidgets.QCheckBox("Ignorer ce qui dépasse sous le nez (pince ou porte-outil du modèle)")
        self.ck_couper.setChecked(True)
        cl.addWidget(self.ck_coulisse)
        cl.addWidget(self.ck_couper)
        r = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Valider le modèle")
        b.clicked.connect(self.valider_modele)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Abandonner")
        b.clicked.connect(self.fermer_session)
        r.addWidget(b)
        r.addStretch(1)
        cl.addLayout(r)
        gl.addWidget(self.cadre)
        self.cadre.setVisible(False)
        lay.addWidget(gb)

        # ---------------------------------------------------------- partage
        r = QtWidgets.QHBoxLayout()
        self.b_tableur = QtWidgets.QPushButton("Reprendre le tableur de la macro")
        self.b_tableur.setToolTip("Lit les cotes du tableur « MachineParams » de l'ancienne macro Excitech")
        self.b_tableur.clicked.connect(self.reprendre_tableur)
        self.b_tableur.setVisible(self.doc_cam is not None and self.doc_cam.getObject("MachineParams") is not None)
        r.addWidget(self.b_tableur)
        b = QtWidgets.QPushButton("Nouveau")
        b.clicked.connect(self.nouveau)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Importer (.zip)…")
        b.clicked.connect(self.importer_zip)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Exporter (.zip)…")
        b.clicked.connect(self.exporter_zip)
        r.addWidget(b)
        self.b_supprimer = QtWidgets.QPushButton("Supprimer")
        self.b_supprimer.clicked.connect(self.supprimer)
        r.addWidget(self.b_supprimer)
        r.addStretch(1)
        lay.addLayout(r)

        r = QtWidgets.QHBoxLayout()
        self.etat = QtWidgets.QLabel("")
        self.etat.setWordWrap(True)
        r.addWidget(self.etat, 1)
        b = QtWidgets.QPushButton("Enregistrer sous…")
        b.clicked.connect(self.enregistrer_sous)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Enregistrer")
        b.setDefault(True)
        b.clicked.connect(self.enregistrer)
        r.addWidget(b)
        b = QtWidgets.QPushButton("Fermer")
        b.clicked.connect(self.close)
        r.addWidget(b)
        lay.addLayout(r)

        self.remplir()

    # ------------------------------------------------------------ affichage
    def marquer_modifie(self, *_a):
        if not self._remplissage:
            self.modifie = True

    def remplir(self):
        self._remplissage = True
        try:
            self.ed_nom.setText(self.prof.get("nom", ""))
            self.ed_desc.setText(self.prof.get("description", ""))
            if self.prof.get("_fourni"):
                self.lbl_origine.setText("Profil fourni avec l'extension : « Enregistrer » en fait une copie personnelle "
                                         "qui le remplace sur ce poste.")
            elif self.prof.get("_dossier"):
                self.lbl_origine.setText("Dossier du profil : " + self.prof["_dossier"])
            else:
                self.lbl_origine.setText("Profil pas encore enregistré.")
            self.table.setRowCount(0)
            self.lignes = {}
            gras = QtGui.QFont()
            gras.setBold(True)
            fixe = QtCore.Qt.ItemIsEnabled
            for section, alias, _d, unite, desc in M.PARAMS:
                ligne = self.table.rowCount()
                self.table.insertRow(ligne)
                if alias is None:
                    it = QtWidgets.QTableWidgetItem(section)
                    it.setFont(gras)
                    it.setFlags(fixe)
                    self.table.setItem(ligne, 0, it)
                    self.table.setSpan(ligne, 0, 1, 4)
                    continue
                v = self.prof["params"].get(alias)
                for col, txt in enumerate((alias, "%g" % v, unite, desc)):
                    it = QtWidgets.QTableWidgetItem(txt)
                    if col != 1:
                        it.setFlags(fixe)
                    else:
                        it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    self.table.setItem(ligne, col, it)
                self.lignes[alias] = ligne
            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(1, 90)
            self.b_supprimer.setEnabled(bool(self.prof.get("_dossier")) and not self.prof.get("_fourni"))
        finally:
            self._remplissage = False
        self.maj_modele()

    def cellule_modifiee(self, it):
        if self._remplissage or it.column() != 1:
            return
        try:
            _nombre(it.text())
            it.setBackground(QtGui.QBrush())
        except ValueError:
            it.setBackground(QtGui.QBrush(QtGui.QColor("#ffcdd2")))
        self.modifie = True

    def maj_modele(self):
        b = self.prof.get("broche")
        if self.modele_en_attente == "retirer":
            txt = "Le modèle sera retiré à l'enregistrement : broche dessinée à partir des cotes."
        elif self.modele_en_attente is not None:
            m = self.modele_en_attente
            txt = ("Nouveau modèle prêt : %s, contrôlé avec %d volume(s) englobant(s). "
                   "Cliquer « Enregistrer » pour l'ajouter au profil."
                   % (os.path.basename(m.get("nom_origine") or m["source"]), len(m["enveloppe"])))
        elif b:
            txt = ("Modèle : %s, contrôlé avec %d volume(s) englobant(s)%s."
                   % (b.get("fichier_origine", b.get("source")), len(b.get("enveloppe") or []),
                      ", coulisse Z comprise" if b.get("inclut_coulisse") else ""))
        else:
            txt = "Pas de modèle : la broche est dessinée à partir des cotes (nez, corps, bride)."
        self.lbl_modele.setText(txt)
        self.b_realigner.setEnabled(bool(b) and self.modele_en_attente is None and bool(self.prof.get("_dossier")))
        self.b_retirer.setEnabled(bool(b) or (self.modele_en_attente not in (None, "retirer")))

    def lire_tableau(self):
        erreurs = []
        for alias, ligne in self.lignes.items():
            try:
                self.prof["params"][alias] = _nombre(self.table.item(ligne, 1).text())
            except ValueError:
                erreurs.append(alias)
        self.prof["nom"] = self.ed_nom.text().strip() or "Machine"
        self.prof["description"] = self.ed_desc.text().strip()
        return erreurs

    def dire(self, txt):
        self.etat.setText(txt)

    # ---------------------------------------------------- alignement du STEP
    def importer_step(self):
        chemin, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Modèle 3D de la broche", "", "Modèles 3D (*.step *.stp *.STEP *.STP *.iges *.igs *.brep *.brp)")
        if not chemin:
            return
        self.occupe(True)
        try:
            source = profils.lire_modele(chemin)
        except Exception as e:
            self.occupe(False)
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Lecture impossible :\n%s" % e)
            return
        self.occupe(False)
        self.ouvrir_session(chemin, source, App.Placement(), os.path.basename(chemin))

    def realigner(self):
        b = self.prof.get("broche")
        if not b:
            return
        chemin = os.path.join(self.prof["_dossier"], b["source"])
        try:
            source = profils.lire_modele(chemin)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Fichier source illisible :\n%s" % e)
            return
        self.ck_coulisse.setChecked(bool(b.get("inclut_coulisse")))
        self.ck_couper.setChecked(bool(b.get("couper_sous_nez", True)))
        self.ouvrir_session(chemin, source, profils.placement_depuis_json(b.get("alignement")),
                            b.get("fichier_origine"), deja_aligne=True)

    def ouvrir_session(self, chemin, source, alignement, nom_origine, deja_aligne=False):
        self.fermer_session()
        d = App.newDocument(NOM_DOC_ALIGNEMENT)
        d.Label = "Alignement de la broche"
        o = d.addObject("Part::Feature", "Broche")
        o.Label = "Broche importée"
        o.Shape = source
        o.Placement = alignement
        self.lire_tableau()
        P = self.prof["params"]
        r_nez = max(P["BrocheNezDiam"] / 2, 10.0)
        outil = d.addObject("Part::Feature", "RepereOutil")
        outil.Label = "Repère · outil (vers le bas)"
        outil.Shape = Part.makeCylinder(4, 60, App.Vector(0, 0, -60))
        nez = d.addObject("Part::Feature", "RepereNez")
        nez.Label = "Repère · nez de broche"
        nez.Shape = Part.makeCylinder(r_nez, 0.5, App.Vector(0, 0, -0.5))
        L = max(P["DecalagePoutre"], 150.0)
        fleche = Part.makeCylinder(5, L, App.Vector(0, 0, 0), App.Vector(1, 0, 0))
        fleche = fleche.fuse(Part.makeCone(14, 0, 40, App.Vector(L, 0, 0), App.Vector(1, 0, 0)))
        fl = d.addObject("Part::Feature", "ReperePoutre")
        fl.Label = "Repère · côté poutre"
        fl.Shape = fleche
        d.recompute()
        if App.GuiUp:
            try:
                o.ViewObject.ShapeColor = M.COULEURS["broche"]
                o.ViewObject.Transparency = 25
                outil.ViewObject.ShapeColor = M.COULEURS["outil"]
                nez.ViewObject.ShapeColor = (0.6, 0.6, 0.6)
                nez.ViewObject.Transparency = 50
                fl.ViewObject.ShapeColor = M.COULEURS["hotte"]
                for x in (outil, nez, fl):
                    x.ViewObject.Selectable = False
                v = Gui.ActiveDocument.ActiveView
                v.viewIsometric()
                v.fitAll()
            except Exception:
                pass
        self.session = {"doc": d.Name, "obj": o.Name, "source": source, "chemin": chemin,
                        "A": alignement, "nom_origine": nom_origine, "aligne": deja_aligne}
        self.cadre.setVisible(True)
        if deja_aligne:
            self.etape("Alignement actuel affiché. Corriger si besoin, puis « Valider le modèle ».")
        else:
            self.etape("1. Dans la vue 3D, clique le <b>bord circulaire du nez de broche</b> (la face d'où sort "
                       "le porte-outil), ou cette face elle-même.<br>2. Clique « Aligner sur la sélection ».")

    def etape(self, html):
        self.lbl_etape.setText(html)

    def objet_session(self):
        if not self.session:
            return None, None
        d = App.getDocument(self.session["doc"]) if self.session["doc"] in App.listDocuments() else None
        if d is None:
            self.session = None
            self.cadre.setVisible(False)
            return None, None
        return d, d.getObject(self.session["obj"])

    def aligner(self):
        d, o = self.objet_session()
        if o is None:
            return
        sel = [s for s in Gui.Selection.getSelectionEx(d.Name) if s.SubObjects]
        if not sel:
            self.etape("Rien n'est sélectionné : clique d'abord le bord circulaire du nez de broche dans la vue 3D.")
            return
        try:
            centre, axe = profils.repere_selection(sel[0].SubObjects[0])
        except ValueError as e:
            self.etape(str(e))
            return
        A = profils.aligner(self.session["A"], o.Shape.BoundBox.Center, centre, axe)
        A = profils.equerrer(profils.forme_alignee(self.session["source"], A), A)
        A = profils.orienter_bride(profils.forme_alignee(self.session["source"], A), A)
        self.appliquer(A)
        Gui.Selection.clearSelection()
        self.session["aligne"] = True
        self.etape("Aligné. Vérifie dans la vue : le nez sur le disque gris, l'outil jaune dessous, et la fixation "
                   "de la broche du côté de la <b>flèche bleue</b> (côté poutre).<br>Sinon : « Tourner de » 90° "
                   "ou « Retourner ». Puis « Valider le modèle ».")

    def transformer(self, f, *args):
        d, o = self.objet_session()
        if o is None:
            return
        self.appliquer(f(self.session["A"], *args))

    def appliquer(self, A):
        d, o = self.objet_session()
        if o is None:
            return
        self.session["A"] = A
        o.Placement = A
        d.recompute()
        try:
            Gui.ActiveDocument.ActiveView.fitAll()
        except Exception:
            pass

    def valider_modele(self):
        d, o = self.objet_session()
        if o is None:
            return
        if not self.session["aligne"]:
            r = QtWidgets.QMessageBox.question(
                self, "CAM Machinist", "Le modèle n'a pas été aligné sur le nez de broche. Valider quand même ?")
            if r != QtWidgets.QMessageBox.Yes:
                return
        self.occupe(True)
        try:
            m = profils.preparer_modele(self.session["chemin"], self.session["source"], self.session["A"],
                                        self.ck_coulisse.isChecked(), self.ck_couper.isChecked(),
                                        nom_origine=self.session["nom_origine"])
        except Exception as e:
            self.occupe(False)
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Préparation du modèle impossible :\n%s" % e)
            return
        self.occupe(False)
        self.modele_en_attente = m
        self.modifie = True
        self.fermer_session()
        self.maj_modele()
        self.dire("Modèle prêt. « Enregistrer » pour l'ajouter au profil.")

    def fermer_session(self):
        if self.session and self.session["doc"] in App.listDocuments():
            try:
                App.closeDocument(self.session["doc"])
            except Exception:
                pass
        self.session = None
        self.cadre.setVisible(False)
        if self.doc_cam is not None and self.doc_cam.Name in App.listDocuments():
            try:
                App.setActiveDocument(self.doc_cam.Name)
                Gui.activateDocument(self.doc_cam.Name)
            except Exception:
                pass

    def retirer_modele(self):
        if self.modele_en_attente not in (None, "retirer") and not self.prof.get("broche"):
            self.modele_en_attente = None
        else:
            self.modele_en_attente = "retirer"
        self.modifie = True
        self.maj_modele()

    # ----------------------------------------------------- enregistrement
    def enregistrer(self, ident=None):
        erreurs = self.lire_tableau()
        if erreurs:
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Valeurs illisibles : " + ", ".join(erreurs))
            return None
        self.occupe(True)
        try:
            ident = profils.enregistrer(self.prof, ident=ident or self.prof.get("_id"),
                                        modele_en_attente=self.modele_en_attente)
        except Exception as e:
            self.occupe(False)
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Enregistrement impossible :\n%s" % e)
            return None
        self.occupe(False)
        self.prof = profils.charger(ident)
        self.modele_en_attente = None
        self.modifie = False
        self.remplir()
        self.dire("Profil « %s » enregistré." % self.prof["nom"])
        if self.rappel:
            try:
                self.rappel(ident)
            except Exception as e:
                M.avert("Mise à jour du panneau : %s" % e)
        return ident

    def enregistrer_sous(self):
        nom, ok = QtWidgets.QInputDialog.getText(self, "CAM Machinist", "Nom du nouveau profil :",
                                                 text=self.ed_nom.text() + " (copie)")
        if not ok or not nom.strip():
            return
        ident = profils.identifiant(nom)
        info = profils.lister().get(ident)
        if info and not info["fourni"]:
            r = QtWidgets.QMessageBox.question(self, "CAM Machinist", "Le profil « %s » existe : le remplacer ?" % info["nom"])
            if r != QtWidgets.QMessageBox.Yes:
                return
        self.ed_nom.setText(nom.strip())
        self.enregistrer(ident)

    def nouveau(self):
        if not self.confirmer_abandon():
            return
        self.fermer_session()
        self.prof = profils.nouveau()
        self.modele_en_attente = None
        self.modifie = True
        self.remplir()

    def exporter_zip(self):
        if self.modifie or not self.prof.get("_id"):
            if self.enregistrer() is None:
                return
        chemin, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Exporter le profil", self.prof["_id"] + ".zip",
                                                           "Profil CAM Machinist (*.zip)")
        if not chemin:
            return
        if not chemin.lower().endswith(".zip"):
            chemin += ".zip"
        profils.exporter_zip(self.prof["_id"], chemin)
        self.dire("Profil exporté : " + chemin)

    def importer_zip(self):
        if not self.confirmer_abandon():
            return
        chemin, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Importer un profil", "", "Profil CAM Machinist (*.zip)")
        if not chemin:
            return
        try:
            ident = profils.importer_zip(chemin)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "CAM Machinist", "Import impossible :\n%s" % e)
            return
        self.prof = profils.charger(ident)
        self.modele_en_attente = None
        self.modifie = False
        self.remplir()
        self.dire("Profil « %s » importé." % self.prof["nom"])
        if self.rappel:
            self.rappel(ident)

    def supprimer(self):
        ident = self.prof.get("_id")
        if not ident or self.prof.get("_fourni"):
            return
        r = QtWidgets.QMessageBox.question(self, "CAM Machinist", "Supprimer le profil « %s » de ce poste ?" % self.prof["nom"])
        if r != QtWidgets.QMessageBox.Yes:
            return
        profils.supprimer(ident)
        restant = profils.lister()
        self.prof = profils.charger(ident) if ident in restant else (
            profils.charger(sorted(restant)[0]) if restant else profils.nouveau())
        self.modele_en_attente = None
        self.modifie = False
        self.remplir()
        self.dire("Profil supprimé.")
        if self.rappel and self.prof.get("_id"):
            self.rappel(self.prof["_id"])

    def reprendre_tableur(self):
        p = profils.reprendre_tableur(self.doc_cam)
        if not p:
            self.dire("Pas de tableur « MachineParams » lisible dans le document.")
            return
        self._remplissage = True
        try:
            for alias, v in p.items():
                if alias in self.lignes:
                    self.table.item(self.lignes[alias], 1).setText("%g" % v)
        finally:
            self._remplissage = False
        self.modifie = True
        self.dire("%d cote(s) reprise(s) du tableur. Vérifier puis enregistrer." % len(p))

    # ----------------------------------------------------------- divers
    def occupe(self, oui):
        if oui:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def confirmer_abandon(self):
        if not self.modifie:
            return True
        r = QtWidgets.QMessageBox.question(self, "CAM Machinist", "Abandonner les modifications non enregistrées ?")
        return r == QtWidgets.QMessageBox.Yes

    def closeEvent(self, ev):
        if not self.confirmer_abandon():
            ev.ignore()
            return
        self.fermer_session()
        if self in _OUVERT:
            _OUVERT.remove(self)
        super(Editeur, self).closeEvent(ev)
