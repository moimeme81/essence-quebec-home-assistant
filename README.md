# ⛽ Régie Essence Québec pour Home Assistant

Une intégration personnalisée pour Home Assistant qui récupère en temps réel les prix de l'essence au Québec, directement depuis les données ouvertes de la Régie de l'énergie du Québec.

## ✨ Fonctionnalités

* **Configuration simple (UI) :** Fini le YAML ! Cherchez et sélectionnez votre station directement via des menus déroulants (Région > Ville > Bannière > Station).
* **Trois types de carburant :** Crée automatiquement des capteurs pour l'essence Ordinaire, Super et le Diesel.
* **Mise à jour paramétrable :** Choisissez la fréquence de rafraîchissement (par défaut : 60 minutes, minimum : 5 minutes).
* **Coordonnées GPS intégrées :** Les capteurs incluent la latitude et la longitude, permettant une intégration native avec la carte (Map) de Home Assistant.
* **Moteur de recherche intelligent :** Inclut un service personnalisé (`regie_essence_quebec.find_closest_stations`) capable de calculer en temps réel les stations les plus proches ou les moins chères dans un rayon donné autour de vous !
* **Configuration simple :** La configuration des station se fait via 2 processus diférent, soit en sélectionant la région/ville/bannière et l'adresse ou les adresses **ou** via la recherche avancée qui permet de voir toute les stations d'une bannière ou en écrivant l'adresse directement (match partiel possible)

---

## Installation

### Méthode 1 : Via HACS (Recommandé)

[![Installer via HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=moimeme81&repository=essence-quebec-home-assistant&category=integration)

1. Ouvrez HACS dans Home Assistant.
2. Cliquez sur **Intégrations**.
3. Cliquez sur les 3 petits points en haut à droite et sélectionnez **Dépôts personnalisés** (Custom repositories).
4. Ajoutez l'URL de ce dépôt GitHub (`https://github.com/moimeme81/essence-quebec-home-assistant`) et choisissez la catégorie **Intégration**.
5. Cliquez sur **Télécharger** (Download).
6. Redémarrez Home Assistant.


### Méthode 2 : Manuelle

1. Téléchargez le contenu de ce dépôt.
2. Copiez le dossier `custom_components/regie_essence_quebec` dans le dossier `custom_components` de votre configuration Home Assistant.
3. **Redémarrez Home Assistant**.

## ⚙️ Configuration

1. Allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur **+ Ajouter une intégration**.
3. Cherchez **Régie Essence Québec**.
4. Laissez-vous guider par les menus pour trouver la station que vous souhaitez surveiller.
5. C'est fait ! Un nouvel appareil sera créé avec vos capteurs de prix.
*Note : Vous pouvez ajouter l'intégration plusieurs fois si vous souhaitez surveiller plusieurs stations spécifiques.*

---


## 🚀 Utilisation Avancée

### 1. Affichage sur une carte (Map Card)
Puisque les capteurs incluent les attributs `latitude` et `longitude`, vous pouvez afficher votre station directement sur une carte dans votre tableau de bord. Cliquer sur l'icône affichera le prix actuel !

```yaml
type: map
title: Ma Station d'Essence
default_zoom: 14
entities:
  - entity: sensor.votre_station_ordinaire
```

### 2. Le Service "Trouver les plus proches / moins chères"
L'intégration ajoute un service puissant nommé `regie_essence_quebec.find_closest_stations`.
En lui fournissant vos coordonnées GPS actuelles (via votre téléphone ou votre zone "Maison"), il calcule la distance avec toutes les stations du Québec et vous renvoie les meilleures options.

Options configurables du service :

`latitude` / `longitude` : Vos coordonnées de départ.

`limit` : Nombre de stations à retourner (ex: 3).

`radius` : Rayon de recherche en kilomètres (ex: 10). 

`gas_type` : Type d'essence recherché (`Régulier`, `Super`, ou `Diesel`).

#### helpers:

il est possible de définir des helpers qui déterminent le type d'essence recherché et le rayon de recherche

<table>
  <tr>
    <td valign="top" align="center">
      <p>Helper rayon de recherche:</p>
      <img src="helper_rayon.png" width="400" alt="First Image">
      <p>Remplacer la valeur de "radius" par: "{{ states('input_number.rayon_recherche_essence') | float }}"</p>
    </td>
    <td valign="top" align="center">
      <p>Helper type d'essence:</p>
      <img src="helper_type.png" width="400" alt="Second Image">
      <p>Remplacer la valeur de "gas_type: par "{{ states('input_select.type_essence_recherche') }}"</p>
    </td>
  </tr>
</table>




### 3. Scripts : Notifications Interactives avec Android Auto / Google Maps
Voici deux scripts prêts à l'emploi que vous pouvez ajouter à votre Home Assistant.
Ils utilisent la géolocalisation de votre téléphone pour trouver l'essence autour de vous, et vous envoient une notification avec des boutons cliquables pour lancer directement la navigation GPS vers la station choisie !

⚠️ Important : Remplacez `sensor.votre_telephone` et `notify.mobile_app_votre_telephone` par les vraies entités de votre appareil.

## Script A : Trouver les 3 stations les plus proches

```yaml
alias: "Essence: Les 3 Plus Proches"
sequence:
  - action: regie_essence_quebec.find_closest_stations
    data:
      latitude: "{{ state_attr(''device_tracker.votre_telephone', 'Location')[0] }}"
      longitude: "{{ state_attr(''device_tracker.votre_telephone', 'Location')[1] }}"
      limit: 3
      radius: 50
      gas_type: "Régulier"
    response_variable: gas_results
  - action: notify.mobile_app_votre_telephone
    data:
      title: "⛽ Les 3 Plus Proches"
      message: >-
        {% for station in gas_results.closest %} 
        {{ loop.index }}. {{ station.brand }} - {{ station.distance_km }} km ({{ station.target_price }}¢)
        📍 {{ station.Address }}
        
        {% endfor %}
      data:
        actions: >
          {% set limit = gas_results.closest | length %}
          {% set limit = 3 if limit > 3 else limit %}
          {% set ns = namespace(items=[]) %}
          {% for i in range(limit) %}
            {% set station = gas_results.closest[i] %}
            {% set short_brand = station.brand | truncate(6, true, '') %}
            {% set ns.items = ns.items + [
              {
                "action": "URI", 
                "title": "📍 #" ~ (i + 1) ~ " " ~ short_brand, 
                "uri": "[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=)" ~ station.latitude ~ "," ~ station.longitude 
              }
            ] %}
          {% endfor %}
          {{ ns.items }}
mode: single
icon: mdi:map-marker-distance
```
## Script B : Trouver les 3 stations les moins chères (Rayon de 10km)

```yaml
alias: "Essence: Les 3 Moins Chères (Rayon 10km)"
sequence:
  - action: regie_essence_quebec.find_closest_stations
    data:
      latitude: "{{ state_attr(''device_tracker.votre_telephone_, 'Location')[0] }}"
      longitude: "{{ state_attr(''device_tracker.votre_telephone, 'Location')[1] }}"
      limit: 3
      radius: 10
      gas_type: "Régulier"
    response_variable: gas_results
  - action: notify.mobile_app_votre_telephone
    data:
      title: "💸 Les 3 Moins Chères (10km)"
      message: >-
        {% for station in gas_results.cheapest %} 
        {{ loop.index }}. {{ station.brand }} - {{ station.target_price }}¢ ({{ station.distance_km }} km)
        📍 {{ station.Address }}
        
        {% endfor %}
      data:
        actions: >
          {% set limit = gas_results.cheapest | length %}
          {% set limit = 3 if limit > 3 else limit %}
          {% set ns = namespace(items=[]) %}
          {% for i in range(limit) %}
            {% set station = gas_results.cheapest[i] %}
            {% set short_brand = station.brand | truncate(6, true, '') %}
            {% set ns.items = ns.items + [
              {
                "action": "URI", 
                "title": "💸 #" ~ (i + 1) ~ " " ~ short_brand, 
                "uri": "[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=)" ~ station.latitude ~ "," ~ station.longitude 
              }
            ] %}
          {% endfor %}
          {{ ns.items }}
mode: single
icon: mdi:cash-multiple
```

## À faire
- [ ] Ajouter les logo des marque
- [ ] Créer des blueprint
- [ ] Ajouter sensor de tendance
- [ ] Consolider traduction
- [ ] Automatisation de zone et de proximité
- [ ] Ajout de possibilités de conversion de devise (utile pour les touriste)


## Mentions légales
Cette intégration n'est pas affiliée à la Régie de l'énergie du Québec ni au gouvernement du Québec. Elle extrait simplement les données publiques rendues disponibles sur leur carte interactive.
