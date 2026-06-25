# Author: Stian Skogbrott
# License: Apache-2.0
"""Extended 75-item benchmark dataset for REMORA research (25 items × 3 domains).

All items are in Norwegian by design — the extended benchmark targets Norwegian-language
comprehension across three domains:
  - DCE (dce_ext): Norwegian debt-collection and prescription law (inkassoloven, foreldelsesloven).
  - SCI (sci_ext): Norwegian-language scientific fact-checking (biology, physics, climate).
  - FACT (fact_ext): Norwegian-language general knowledge (geography, history, zoology).

Norwegian is the deployment language for REMORA's primary use case (DCE / Mine Docs).
The extended benchmark intentionally tests the full Norwegian pipeline end-to-end."""
from __future__ import annotations
from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType

_DCE = [
    ("dce_e01","Er et inkassosalær på kr 700 for et krav på kr 200 i strid med inkassoloven § 17?",True),
    ("dce_e02","Kan et inkassosalær overstige hovedkravet hvis kravet er under kr 500?",False),
    ("dce_e03","Er maksimalt inkassosalær fastsatt i inkassoforskriften?",True),
    ("dce_e04","Kan inkassator kreve fullt salær ved frivillig betaling innen betalingsfristen?",False),
    ("dce_e05","Kan inkassator sende inkassovarsel samme dag som fakturaen forfaller?",False),
    ("dce_e06","Er 14 dager minstekravet til betalingsfrist i inkassovarsel etter inkassoloven?",True),
    ("dce_e07","Kan purregebyr legges til kravet uten at inkassovarsel er sendt?",False),
    ("dce_e08","Er maksimalt purregebyr regulert i norsk lov?",True),
    ("dce_e09","Er den alminnelige foreldelsesfristen i Norge 3 år?",True),
    ("dce_e10","Avbrytes foreldelse ved at skyldner sender en SMS med spørsmål om kravet?",False),
    ("dce_e11","Kan en kreditor gjenopplive et foreldet krav ved å sende nytt inkassokrav?",False),
    ("dce_e12","Avbrytes foreldelse dersom skyldner foretar delvis betaling på kravet?",True),
    ("dce_e13","Er foreldelsesfristen for pantegjeld i fast eiendom 10 år?",True),
    ("dce_e14","Har debitor rett til innsyn i hvilke personopplysninger inkassator behandler?",True),
    ("dce_e15","Kan inkassator nekte innsyn hvis kravene ennå ikke er behandlet i retten?",False),
    ("dce_e16","Er inkassator underlagt GDPR som behandlingsansvarlig?",True),
    ("dce_e17","Har debitor rett til å kreve sletting av gjeldsopplysninger etter full betaling?",True),
    ("dce_e18","Forbyr god inkassoskikk å kontakte skyldners arbeidsgiver direkte?",True),
    ("dce_e19","Er det tillatt å splitte ett enkelt krav i to separate inkassosaker for å øke salærgrunnlaget?",False),
    ("dce_e20","Kan inkassator true med straffeanmeldelse for å presse frem betaling av sivilrettslig krav?",False),
    ("dce_e21","Er det tillatt å sende inkassokrav til feil adresse uten å sjekke folkeregisteret?",False),
    ("dce_e22","Løper forsinkelsesrente fra forfallsdato dersom dette er avtalt?",True),
    ("dce_e23","Kan inkassator legge til rettsgebyr uten å ha tatt ut forliksklage?",False),
    ("dce_e24","Er forsinkelsesrentesatsen fastsatt av Finansdepartementet halvårlig?",True),
    ("dce_e25","Kan inkassator kreve dekning for egne kostnader utover de lovregulerte satsene?",False),
]

_SCI = [
    ("sci_e01","DNA er et dobbelttrådet molekyl formet som en dobbel helix.",True),
    ("sci_e02","Alle bakterier er skadelige for mennesker.",False),
    ("sci_e03","Vaksinering mot meslinger forårsaker autisme.",False),
    ("sci_e04","Antibiotika er effektivt mot virusinfeksjoner.",False),
    ("sci_e05","Mitokondrier er organeller som produserer ATP gjennom celleånding.",True),
    ("sci_e06","Mennesker bruker kun 10 prosent av hjernen.",False),
    ("sci_e07","CRISPR-Cas9 er en teknikk som brukes til å redigere DNA.",True),
    ("sci_e08","Røyking er en dokumentert risikofaktor for lungekreft.",True),
    ("sci_e09","Insulin produseres i bukspyttkjertelen.",True),
    ("sci_e10","Selvmedisinering med antibiotika bidrar til økt antibiotikaresistens.",True),
    ("sci_e11","Vann koker ved 100 grader Celsius ved normalt lufttrykk.",True),
    ("sci_e12","Lys beveger seg raskere i vann enn i vakuum.",False),
    ("sci_e13","Diamant er den hardeste naturlig forekommende substansen.",True),
    ("sci_e14","Hydrogen er det tyngste grunnstoffet i periodesystemet.",False),
    ("sci_e15","CO2 er en drivhusgass som bidrar til global oppvarming.",True),
    ("sci_e16","Solen er en stjerne av typen gul dverg.",True),
    ("sci_e17","E=mc² ble formulert av Albert Einstein.",True),
    ("sci_e18","Lyd kan reise gjennom vakuum.",False),
    ("sci_e19","Jordens kjerne er primært sammensatt av oksygen.",False),
    ("sci_e20","Jordens atmosfære inneholder mest nitrogen.",True),
    ("sci_e21","Isbreer på Grønland smelter raskere nå enn for 50 år siden.",True),
    ("sci_e22","Platetektonikk er en veldokumentert geologisk teori.",True),
    ("sci_e23","Vitamin C kan forhindre en allerede påbegynt forkjølelse.",False),
    ("sci_e24","Regelmessig fysisk aktivitet reduserer risikoen for hjertesykdom.",True),
    ("sci_e25","Alle fettstoffer er helseskadelige og bør unngås.",False),
]

_FACT = [
    ("fact_e01","Norge grenser til Sverige, Finland og Russland.",True),
    ("fact_e02","Spania er en del av Skandinavia.",False),
    ("fact_e03","Nilen er verdens lengste elv.",True),
    ("fact_e04","Australia er både et land og et kontinent.",True),
    ("fact_e05","Mount Everest ligger på grensen mellom Nepal og Tibet.",True),
    ("fact_e06","Brasils hovedstad er Rio de Janeiro.",False),
    ("fact_e07","Storbritannia er medlem av EU.",False),
    ("fact_e08","Canada er verdens nest største land i areal.",True),
    ("fact_e09","Andre verdenskrig sluttet i 1945.",True),
    ("fact_e10","Månelandingen Apollo 11 fant sted i 1969.",True),
    ("fact_e11","Den franske revolusjon begynte i 1789.",True),
    ("fact_e12","Kina var verdens første land til å trykke papirpenger.",True),
    ("fact_e13","Napoleon Bonaparte var italiensk statsborger.",False),
    ("fact_e14","Berlinmuren falt i 1989.",True),
    ("fact_e15","Hval er pattedyr, ikke fisker.",True),
    ("fact_e16","Edderkopper er insekter.",False),
    ("fact_e17","Flaggermus er de eneste pattedyrene som aktivt kan fly.",True),
    ("fact_e18","Pingviner lever naturlig på Nordpolen.",False),
    ("fact_e19","En blekksprut har tre hjerter.",True),
    ("fact_e20","Sjiraff har lengre nakke-bein enn neshorn.",True),
    ("fact_e21","Internett ble oppfunnet av Tim Berners-Lee.",False),
    ("fact_e22","Penicillin ble oppdaget av Alexander Fleming.",True),
    ("fact_e23","Den første kommersielle flyvningen fant sted i 1914.",True),
    ("fact_e24","Sjakk ble oppfunnet i India.",True),
    ("fact_e25","DNA-strukturen ble beskrevet av Watson og Crick i 1953.",True),
]

def load_extended_dce() -> list[BenchmarkItem]:
    return [BenchmarkItem(item_id=id_, benchmark="dce_ext", question=q, ground_truth=gt,
        truth_type=GroundTruthType.POLARITY.value) for id_, q, gt in _DCE]

def load_extended_sci() -> list[BenchmarkItem]:
    return [BenchmarkItem(item_id=id_, benchmark="sci_ext", question=q, ground_truth=gt,
        truth_type=GroundTruthType.POLARITY.value) for id_, q, gt in _SCI]

def load_extended_fact() -> list[BenchmarkItem]:
    return [BenchmarkItem(item_id=id_, benchmark="fact_ext", question=q, ground_truth=gt,
        truth_type=GroundTruthType.POLARITY.value) for id_, q, gt in _FACT]

def load_all_extended() -> list[BenchmarkItem]:
    """Return all 75 extended benchmark items (25 DCE + 25 SCI + 25 FACT)."""
    return load_extended_dce() + load_extended_sci() + load_extended_fact()
