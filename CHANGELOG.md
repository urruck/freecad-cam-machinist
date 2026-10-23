# Journal des versions

## 0.2.2 (2026-10-23)

- Axes X et Y corrigés dans le profil Excitech fourni et les valeurs par défaut : table 1600 x 3100, portique qui avance en Y. Le moteur, lui, suivait déjà correctement le profil.
- Bouton « Permuter X et Y » dans l'éditeur de profil : échange en un clic les cotes X/Y de la table et des courses, et l'axe d'avance du portique.

## 0.2.1 (2026-10-23)

- L'extension prend le nom du dépôt : « CAM Machinist » (publiée quelques minutes plus tôt sous le nom « Portique CAM »).
- Adresse de contact dans `package.xml`.

## 0.2.0 (2026-10-23)

- La macro devient une extension FreeCAD : bouton dans la barre d'outils et le menu de l'atelier CAM.
- Import du modèle STEP de la broche, avec assistant d'alignement (nez, équerrage, côté poutre).
- Enveloppe de contrôle calculée à partir du modèle, et « Mesurer ici » pour la distance exacte.
- Profils machine enregistrés hors des documents, export et import en `.zip`.
- Mise en place (origine sur la table, dessus de table) réglée par Job.
- Nouvelle gravité « FRÔLEMENT » : garde positive mais sous la marge demandée.

## 0.1 (2026-10-22)

- Macro `Excitech_Bocal.FCMacro` : machine paramétrique, suivi du parcours, contrôle des collisions et des courses.
