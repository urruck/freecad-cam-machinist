# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# Portique CAM · FabLab Le Boc@l, Centre Social et Socioculturel du Chemillois
"""Commandes et bouton dans l'atelier CAM (chargé au démarrage de FreeCAD)."""

import os

import FreeCAD as App
import FreeCADGui as Gui

ICONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons", "portiquecam.svg")
ANCRE = "CAM_Inspect"            # entrée de menu placée après « Inspecter le G-code »
BARRE = "Tool Commands"          # barre d'outils « Outils » de l'atelier CAM (nom interne)


class CommandePanneau:
    def GetResources(self):
        return {"Pixmap": ICONE,
                "MenuText": "Portique CAM",
                "ToolTip": "Portique et broche de la machine : suivi du parcours d'outil, "
                           "contrôle des collisions et des courses"}

    def Activated(self):
        from freecad.portiquecam import panneau
        panneau.ouvrir()

    def IsActive(self):
        return App.ActiveDocument is not None


class CommandeProfils:
    def GetResources(self):
        return {"Pixmap": ICONE,
                "MenuText": "Profils machine…",
                "ToolTip": "Cotes de la machine, modèle STEP de la broche, import et export de profils"}

    def Activated(self):
        from freecad.portiquecam import editeur, panneau
        p = panneau.instance()
        editeur.ouvrir(p.ident() if p is not None else None, App.ActiveDocument,
                       rappel=p.profil_enregistre if p is not None else None)

    def IsActive(self):
        return True


class Manipulateur:
    """Ajoute les commandes à la barre d'outils et au menu de l'atelier CAM.
    L'ancre n'existe que dans l'atelier CAM : les autres ateliers ne sont pas touchés."""

    def modifyToolBars(self):
        try:
            if Gui.activeWorkbench().name() not in ("CAMWorkbench", "PathWorkbench"):
                return []
        except Exception:
            return []
        return [{"append": "PortiqueCAM_Panneau", "toolBar": BARRE}]

    def modifyMenuBar(self):
        return [{"append": "PortiqueCAM_Profils", "menuItem": ANCRE},
                {"append": "PortiqueCAM_Panneau", "menuItem": ANCRE}]


Gui.addCommand("PortiqueCAM_Panneau", CommandePanneau())
Gui.addCommand("PortiqueCAM_Profils", CommandeProfils())
if hasattr(Gui, "addWorkbenchManipulator"):
    Gui.addWorkbenchManipulator(Manipulateur())
