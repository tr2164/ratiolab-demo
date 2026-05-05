"""
Transcript Discovery Agent.

Two acquisition strategies:
  1. Web search (Tavily) → filter candidates → download PDFs
  2. Direct investor-relations page scraping → find PDF links → download

Saves discovered transcripts into the TRANSCRIPTS_DIR with a normalised filename.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings, get_ssl_verify
from app.services.earnings_call_service import get_transcripts_dir, _parse_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known investor-relations page roots (best-effort free sources)
# ---------------------------------------------------------------------------
IR_ROOTS: dict[str, str] = {
    # ── Mega-cap Tech ───────────────────────────────────────────────────────
    "AAPL":  "https://investor.apple.com",
    "MSFT":  "https://www.microsoft.com/en-us/investor",
    "GOOGL": "https://abc.xyz/investor",
    "GOOG":  "https://abc.xyz/investor",
    "AMZN":  "https://ir.aboutamazon.com",
    "META":  "https://investor.fb.com",
    "NVDA":  "https://investor.nvidia.com",
    "TSLA":  "https://ir.tesla.com",
    # ── Semiconductors ──────────────────────────────────────────────────────
    "AVGO":  "https://investors.broadcom.com",
    "QCOM":  "https://investor.qualcomm.com",
    "TXN":   "https://ir.ti.com",
    "AMD":   "https://ir.amd.com",
    "INTC":  "https://www.intc.com",
    "MU":    "https://investors.micron.com",
    "AMAT":  "https://ir.appliedmaterials.com",
    "LRCX":  "https://investor.lamresearch.com",
    "KLAC":  "https://ir.kla.com",
    "ADI":   "https://investor.analog.com",
    "MCHP":  "https://investor.microchip.com",
    "NXPI":  "https://investors.nxp.com",
    "ON":    "https://www.onsemi.com/site/en/investors",
    "SWKS":  "https://investors.skyworkssolutions.com",
    "QRVO":  "https://ir.qorvo.com",
    "MRVL":  "https://investor.marvell.com",
    "MPWR":  "https://ir.monolithicpower.com",
    "TER":   "https://teradyne.com/investors",
    "ENTG":  "https://investors.entegris.com",
    "MKSI":  "https://ir.mksinst.com",
    # ── Enterprise Software / Cloud ─────────────────────────────────────────
    "CRM":   "https://investor.salesforce.com",
    "ORCL":  "https://investor.oracle.com",
    "IBM":   "https://www.ibm.com/investor",
    "NOW":   "https://ir.servicenow.com",
    "INTU":  "https://investors.intuit.com",
    "ADBE":  "https://www.adobe.com/investor-relations",
    "CSCO":  "https://investor.cisco.com",
    "ACN":   "https://investor.accenture.com",
    "WDAY":  "https://investor.workday.com",
    "ANSS":  "https://ir.ansys.com",
    "PTC":   "https://ir.ptc.com",
    "CDNS":  "https://investors.cadence.com",
    "SNPS":  "https://ir.synopsys.com",
    "HUBS":  "https://ir.hubspot.com",
    "DDOG":  "https://investors.datadoghq.com",
    "SNOW":  "https://investors.snowflake.com",
    "MDB":   "https://investors.mongodb.com",
    "ZS":    "https://ir.zscaler.com",
    "CRWD":  "https://ir.crowdstrike.com",
    "PANW":  "https://investors.paloaltonetworks.com",
    "FTNT":  "https://investor.fortinet.com",
    "OKTA":  "https://investor.okta.com",
    "TWLO":  "https://investors.twilio.com",
    "DOCU":  "https://ir.docusign.com",
    "PLTR":  "https://investors.palantir.com",
    "PAYC":  "https://investors.paycom.com",
    "PCTY":  "https://investors.paylocity.com",
    "CDAY":  "https://ir.ceridian.com",
    "NET":   "https://investors.cloudflare.com",
    "ANET":  "https://investors.arista.com",
    # ── Hardware / Devices ──────────────────────────────────────────────────
    "HPQ":   "https://investor.hp.com",
    "HPE":   "https://investors.hpe.com",
    "DELL":  "https://investors.dell.com",
    # ── Financials – Banks ──────────────────────────────────────────────────
    "JPM":   "https://www.jpmorganchase.com/ir",
    "BAC":   "https://investor.bankofamerica.com",
    "WFC":   "https://www.wellsfargo.com/invest_relations",
    "C":     "https://www.citigroup.com/citi/investor",
    "GS":    "https://www.goldmansachs.com/investor-relations",
    "MS":    "https://www.morganstanley.com/ir",
    "USB":   "https://ir.usbank.com",
    "PNC":   "https://www.pnc.com/en/about-pnc/investor-relations.html",
    "TFC":   "https://ir.truist.com",
    "COF":   "https://ir.capitalone.com",
    "BK":    "https://www.bnymellon.com/us/en/investor-relations",
    "STT":   "https://investors.statestreet.com",
    "SCHW":  "https://schwabir.com",
    "AXP":   "https://ir.americanexpress.com",
    "DFS":   "https://investorrelations.discover.com",
    # ── Financials – Insurance ──────────────────────────────────────────────
    "PRU":   "https://investor.prudential.com",
    "MET":   "https://investor.metlife.com",
    "AFL":   "https://investors.aflac.com",
    "ALL":   "https://ir.allstate.com",
    "TRV":   "https://investor.travelers.com",
    "PGR":   "https://investors.progressive.com",
    "CB":    "https://investors.chubb.com",
    "HIG":   "https://ir.thehartford.com",
    "AIG":   "https://ir.aig.com",
    "LNC":   "https://ir.lfg.com",
    "GL":    "https://ir.globe.life",
    "UNM":   "https://ir.unum.com",
    "RLI":   "https://ir.rlicorp.com",
    "CINF":  "https://www.cinfin.com/investors",
    # ── Financials – Capital Markets / Exchanges ────────────────────────────
    "BLK":   "https://ir.blackrock.com",
    "SPGI":  "https://investor.spglobal.com",
    "MCO":   "https://ir.moodys.com",
    "ICE":   "https://ir.theice.com",
    "CME":   "https://investor.cmegroup.com",
    "NDAQ":  "https://ir.nasdaq.com",
    "MMC":   "https://mmc.com/investor-relations",
    "AON":   "https://ir.aon.com",
    "AJG":   "https://www.ajg.com/investor-relations",
    "TROW":  "https://individual.troweprice.com/retail/public/investor-relations",
    "IVZ":   "https://ir.invesco.com",
    "MSCI":  "https://ir.msci.com",
    "VRSK":  "https://ir.verisk.com",
    # ── Financials – Payments ───────────────────────────────────────────────
    "V":     "https://investor.visa.com",
    "MA":    "https://investor.mastercard.com",
    "PYPL":  "https://investor.pypl.com",
    "FIS":   "https://investors.fisglobal.com",
    "FISV":  "https://investors.fiserv.com",
    "GPN":   "https://investors.globalpayments.com",
    "SQ":    "https://investors.block.xyz",
    # ── Healthcare – Managed Care / PBM ────────────────────────────────────
    "UNH":   "https://www.unitedhealthgroup.com/investors.html",
    "CVS":   "https://investors.cvshealth.com",
    "CI":    "https://cignagroup.com/investors",
    "ELV":   "https://ir.elevancehealth.com",
    "HUM":   "https://humana.com/investor-relations",
    "CNC":   "https://ir.centene.com",
    "MOH":   "https://ir.molinahealthcare.com",
    # ── Healthcare – Distribution ───────────────────────────────────────────
    "MCK":   "https://investor.mckesson.com",
    "ABC":   "https://www.amerisourcebergen.com/investors",
    "CAH":   "https://ir.cardinalhealth.com",
    # ── Healthcare – Pharma / Biotech ───────────────────────────────────────
    "JNJ":   "https://investor.jnj.com",
    "ABBV":  "https://investors.abbvie.com",
    "LLY":   "https://investor.lilly.com",
    "MRK":   "https://www.merck.com/investor-relations",
    "PFE":   "https://investors.pfizer.com",
    "AMGN":  "https://investors.amgn.com",
    "BMY":   "https://investors.bms.com",
    "GILD":  "https://investors.gilead.com",
    "BIIB":  "https://investors.biogen.com",
    "REGN":  "https://investor.regeneron.com",
    "VRTX":  "https://investors.vrtx.com",
    "MRNA":  "https://investors.modernatx.com",
    "BNTX":  "https://investors.biontech.de",
    "ALNY":  "https://ir.alnylam.com",
    "SGEN":  "https://investor.seagen.com",
    "INCY":  "https://ir.incyte.com",
    "EXEL":  "https://ir.exelixis.com",
    "HZNP":  "https://ir.horizonpharma.com",
    # ── Healthcare – Devices / Equipment ────────────────────────────────────
    "ABT":   "https://investors.abbott.com",
    "MDT":   "https://investorrelations.medtronic.com",
    "SYK":   "https://ir.stryker.com",
    "BSX":   "https://investors.bostonscientific.com",
    "EW":    "https://ir.edwards.com",
    "BDX":   "https://investors.bd.com",
    "ZBH":   "https://investor.zimmerbiomet.com",
    "ISRG":  "https://isrg.gcs-web.com",
    "TMO":   "https://ir.thermofisher.com",
    "DHR":   "https://investors.danaher.com",
    "IQV":   "https://ir.iqvia.com",
    "A":     "https://investor.agilent.com",
    "ZTS":   "https://ir.zoetis.com",
    "HOLX":  "https://investors.hologic.com",
    "BAX":   "https://investors.baxter.com",
    "HSIC":  "https://ir.henryschein.com",
    # ── Healthcare – Services ───────────────────────────────────────────────
    "HCA":   "https://ir.hcahealthcare.com",
    "THC":   "https://investors.tenethealth.com",
    "UHS":   "https://ir.uhsinc.com",
    "DVA":   "https://ir.davita.com",
    "LH":    "https://ir.labcorp.com",
    "DGX":   "https://ir.questdiagnostics.com",
    # ── Consumer Staples – Food & Beverage ──────────────────────────────────
    "KO":    "https://investors.coca-colacompany.com",
    "PEP":   "https://www.pepsico.com/investors",
    "PG":    "https://pginvestor.com",
    "KHC":   "https://ir.kraftheinzcompany.com",
    "MDLZ":  "https://ir.mondelezinternational.com",
    "GIS":   "https://investors.generalmills.com",
    "K":     "https://investor.kellanova.com",
    "CAG":   "https://www.conagrabrands.com/investor-relations",
    "CPB":   "https://investor.campbells.com",
    "HRL":   "https://ir.hormel.com",
    "SJM":   "https://ir.jmsmucker.com",
    "MKC":   "https://ir.mccormick.com",
    "TSN":   "https://ir.tyson.com",
    "ADM":   "https://investors.adm.com",
    "BG":    "https://ir.bunge.com",
    "HSY":   "https://www.thehersheycompany.com/en_us/investors.html",
    "MNST":  "https://ir.monsterbevcorp.com",
    "TAP":   "https://molsoncoors.com/investors",
    "STZ":   "https://ir.cbrands.com",
    "MO":    "https://investor.altria.com",
    "PM":    "https://www.pmi.com/investor-relations",
    "BTI":   "https://www.bat.com/group/sites/uk__9d9kcy.nsf/vwPagesWebLive/DO9DCKFM",
    # ── Consumer Staples – Household / Personal Care ─────────────────────────
    "CL":    "https://investor.colgatepalmolive.com",
    "KMB":   "https://investor.kimberly-clark.com",
    "CLX":   "https://investors.thecloroxcompany.com",
    "CHD":   "https://ir.churchdwight.com",
    "EL":    "https://ir.elcompanies.com",
    # ── Consumer Discretionary – Retail ─────────────────────────────────────
    "WMT":   "https://stock.walmart.com",
    "COST":  "https://investor.costco.com",
    "TGT":   "https://investors.target.com",
    "HD":    "https://ir.homedepot.com",
    "LOW":   "https://ir.lowes.com",
    "TJX":   "https://ir.tjx.com",
    "ROST":  "https://corp.rossstores.com/investors",
    "BURL":  "https://ir.burlington.com",
    "KR":    "https://ir.kroger.com",
    "ACI":   "https://investor.albertsons.com",
    "BBY":   "https://investors.bestbuy.com",
    "DG":    "https://investor.dollargeneral.com",
    "DLTR":  "https://ir.dollartree.com",
    "FIVE":  "https://ir.fivebelow.com",
    "BJ":    "https://ir.bjswholesale.com",
    "SFM":   "https://investors.sprouts.com",
    "AZO":   "https://ir.autozone.com",
    "ORLY":  "https://ir.oreillyauto.com",
    "AAP":   "https://ir.advanceautoparts.com",
    "TSCO":  "https://ir.tractorsupply.com",
    "DKS":   "https://investors.dicks.com",
    "ULTA":  "https://ir.ulta.com",
    "LULU":  "https://investor.lululemon.com",
    "NKE":   "https://investors.nike.com",
    "ANF":   "https://corporate.abercrombie.com/investors",
    "AEO":   "https://investors.ae.com",
    "URBN":  "https://urbn.com/investor-relations",
    "GPS":   "https://investors.gapinc.com",
    "RL":    "https://investor.ralphlauren.com",
    "PVH":   "https://ir.pvh.com",
    "TPR":   "https://tapestry.com/investor-relations",
    "VFC":   "https://ir.vfc.com",
    "HBI":   "https://ir.hanesbrands.com",
    "CPRI":  "https://ir.capriholdings.com",
    "M":     "https://ir.macys.com",
    "KSS":   "https://investors.kohls.com",
    "JWN":   "https://investor.nordstrom.com",
    "EBAY":  "https://investors.ebayinc.com",
    "ETSY":  "https://investors.etsy.com",
    "W":     "https://investor.wayfair.com",
    "CHWY":  "https://ir.chewy.com",
    # ── Consumer Discretionary – Autos ──────────────────────────────────────
    "GM":    "https://investor.gm.com",
    "F":     "https://shareholder.ford.com",
    "RIVN":  "https://rivian.com/investors",
    "LCID":  "https://ir.lucidmotors.com",
    "AN":    "https://ir.autonation.com",
    "PAG":   "https://ir.penskeautomotive.com",
    "LAD":   "https://investors.lithiamotors.com",
    "KMX":   "https://ir.carmax.com",
    "CVNA":  "https://investors.carvana.com",
    "BWA":   "https://ir.borgwarner.com",
    "APTV":  "https://ir.aptiv.com",
    "LEA":   "https://ir.lear.com",
    "GT":    "https://investor.goodyear.com",
    "VC":    "https://visteon.com/investors",
    # ── Consumer Discretionary – Restaurants ────────────────────────────────
    "MCD":   "https://corporate.mcdonalds.com/corpmcd/investors.html",
    "SBUX":  "https://investor.starbucks.com",
    "YUM":   "https://ir.yum.com",
    "QSR":   "https://rbi.com/investors",
    "DRI":   "https://investor.darden.com",
    "CMG":   "https://ir.chipotle.com",
    "WING":  "https://ir.wingstop.com",
    "SHAK":  "https://investor.shakeshack.com",
    "JACK":  "https://jackinthebox.com/investors",
    "CAKE":  "https://investors.thecheesecakefactory.com",
    "BROS":  "https://investors.dutchbros.com",
    # ── Consumer Discretionary – Hotels / Leisure ────────────────────────────
    "MAR":   "https://investor.marriott.com",
    "HLT":   "https://ir.hilton.com",
    "H":     "https://ir.hyatt.com",
    "WH":    "https://ir.wyndhamhotels.com",
    "CHH":   "https://ir.choicehotels.com",
    "RCL":   "https://ir.royalcaribbean.com",
    "CCL":   "https://carnivalcorp.com/investor-relations",
    "NCLH":  "https://www.nclhltd.com/investors",
    "MGM":   "https://investors.mgmresorts.com",
    "LVS":   "https://ir.sands.com",
    "WYNN":  "https://wynnresorts.com/investors",
    "PENN":  "https://ir.pennentertainment.com",
    "CZR":   "https://investor.caesars.com",
    # ── Communication Services ──────────────────────────────────────────────
    "T":     "https://investors.att.com",
    "VZ":    "https://www.verizon.com/about/investors",
    "TMUS":  "https://investor.t-mobile.com",
    "CHTR":  "https://ir.charter.com",
    "CMCSA": "https://corporate.comcast.com/investors",
    "DIS":   "https://thewaltdisneycompany.com/investor-relations",
    "NFLX":  "https://ir.netflix.net",
    "PARA":  "https://investors.paramount.com",
    "WBD":   "https://ir.wbd.com",
    "FOXA":  "https://investor.foxcorporation.com",
    "FOX":   "https://investor.foxcorporation.com",
    "NWSA":  "https://newscorp.com/investor-relations",
    "NWS":   "https://newscorp.com/investor-relations",
    "NYT":   "https://investors.nytco.com",
    "SPOT":  "https://investors.spotify.com",
    "SNAP":  "https://investor.snap.com",
    "PINS":  "https://investor.pinterest.com",
    "MTCH":  "https://ir.match.com",
    "UBER":  "https://investor.uber.com",
    "LYFT":  "https://investor.lyft.com",
    "IAC":   "https://ir.iac.com",
    # ── Energy – Integrated / E&P ────────────────────────────────────────────
    "XOM":   "https://investor.exxonmobil.com",
    "CVX":   "https://www.chevron.com/investors",
    "COP":   "https://ir.conocophillips.com",
    "EOG":   "https://investors.eogresources.com",
    "OXY":   "https://ir.oxy.com",
    "DVN":   "https://ir.devonenergy.com",
    "FANG":  "https://ir.diamondbackenergy.com",
    "HES":   "https://ir.hess.com",
    "APA":   "https://investor.apachecorp.com",
    "MRO":   "https://ir.marathonoil.com",
    # ── Energy – Refining / Midstream ───────────────────────────────────────
    "PSX":   "https://ir.phillips66.com",
    "VLO":   "https://ir.valero.com",
    "MPC":   "https://ir.marathonpetroleum.com",
    "WMB":   "https://investor.williams.com",
    "OKE":   "https://ir.oneok.com",
    "KMI":   "https://ir.kindermorgan.com",
    "LNG":   "https://ir.cheniere.com",
    "TRGP":  "https://ir.targa.com",
    "ET":    "https://ir.energytransfer.com",
    # ── Energy – Services ───────────────────────────────────────────────────
    "SLB":   "https://investorcenter.slb.com",
    "HAL":   "https://ir.halliburton.com",
    "BKR":   "https://investors.bakerhughes.com",
    # ── Industrials – Aerospace & Defense ────────────────────────────────────
    "BA":    "https://investors.boeing.com",
    "GE":    "https://investors.ge.com",
    "RTX":   "https://ir.rtx.com",
    "LMT":   "https://www.lockheedmartin.com/en-us/investors.html",
    "NOC":   "https://investor.northropgrumman.com",
    "GD":    "https://investors.gd.com",
    "LHX":   "https://investors.l3harris.com",
    "TDG":   "https://ir.transdigm.com",
    "HEI":   "https://ir.heico.com",
    "SPR":   "https://ir.spiritaero.com",
    "AXON":  "https://investor.axon.com",
    # ── Industrials – Building / HVAC ───────────────────────────────────────
    "HON":   "https://investor.honeywell.com",
    "CARR":  "https://ir.carrier.com",
    "OTIS":  "https://ir.otis.com",
    "TT":    "https://investors.tranetechnologies.com",
    "JCI":   "https://ir.johnsoncontrols.com",
    "EMR":   "https://investors.emerson.com",
    "ETN":   "https://ir.eaton.com",
    "ROK":   "https://ir.rockwellautomation.com",
    "PH":    "https://ir.parker.com",
    "FTV":   "https://investors.fortive.com",
    "AME":   "https://ir.ametek.com",
    "ITT":   "https://investors.itt.com",
    "IEX":   "https://www.idexcorp.com/investors",
    "GWW":   "https://ir.grainger.com",
    "FAST":  "https://investor.fastenal.com",
    "MAS":   "https://ir.masco.com",
    # ── Industrials – Heavy Equipment ───────────────────────────────────────
    "CAT":   "https://investors.caterpillar.com",
    "DE":    "https://www.deere.com/en/our-company/investor-relations",
    "PCAR":  "https://investor.paccar.com",
    "CMI":   "https://ir.cummins.com",
    "AGCO":  "https://ir.agcocorp.com",
    "CNH":   "https://ir.cnhindustrial.com",
    # ── Industrials – Homebuilders ──────────────────────────────────────────
    "DHI":   "https://investor.drhorton.com",
    "LEN":   "https://ir.lennar.com",
    "NVR":   "https://investors.nvrinc.com",
    "PHM":   "https://investors.pultegroup.com",
    "TOL":   "https://ir.tollbrothers.com",
    # ── Industrials – Services / Distribution ────────────────────────────────
    "UPS":   "https://ir.ups.com",
    "FDX":   "https://investors.fedex.com",
    "CTAS":  "https://investors.cintas.com",
    "RSG":   "https://republicservices.com/investors",
    "WM":    "https://investors.wm.com",
    "CLH":   "https://ir.cleanharbors.com",
    "ADP":   "https://investor.adp.com",
    "PAYX":  "https://investor.paychex.com",
    "R":     "https://ir.ryder.com",
    "CHRW":  "https://investors.chrobinson.com",
    "EXPD":  "https://investor.expeditors.com",
    "XPO":   "https://xpo.com/investor-relations",
    "GXO":   "https://ir.gxo.com",
    "ODFL":  "https://ir.odfl.com",
    "SAIA":  "https://ir.saiafreight.com",
    "JBHT":  "https://ir.jbhunt.com",
    "WERN":  "https://ir.werner.com",
    "KNX":   "https://ir.knighttrans.com",
    "SCI":   "https://ir.sci.com",
    # ── Transportation – Airlines ────────────────────────────────────────────
    "DAL":   "https://ir.delta.com",
    "UAL":   "https://ir.united.com",
    "AAL":   "https://ir.aa.com",
    "LUV":   "https://investors.southwest.com",
    "JBLU":  "https://ir.jetblue.com",
    "ALK":   "https://investor.alaskaair.com",
    # ── Transportation – Rails ───────────────────────────────────────────────
    "UNP":   "https://www.up.com/investors",
    "CSX":   "https://investors.csx.com",
    "NSC":   "https://norfolksouthern.com/content/nscorp/en/investors",
    "CP":    "https://investor.cpr.ca",
    "CNI":   "https://cn.ca/en/investors",
    # ── Utilities ────────────────────────────────────────────────────────────
    "NEE":   "https://investor.nexteraenergy.com",
    "DUK":   "https://ir.duke-energy.com",
    "SO":    "https://investor.southerncompany.com",
    "D":     "https://investors.dominionenergy.com",
    "AEP":   "https://www.aep.com/investors",
    "EXC":   "https://investors.exeloncorp.com",
    "XEL":   "https://investors.xcelenergy.com",
    "ED":    "https://investor.conedison.com",
    "PCG":   "https://investor.pgecorp.com",
    "EIX":   "https://ir.edisonintl.com",
    "WEC":   "https://investors.wecenergygroup.com",
    "PPL":   "https://pplweb.com/investors",
    "CMS":   "https://investors.cmsenergy.com",
    "ETR":   "https://ir.entergy.com",
    "FE":    "https://ir.firstenergycorp.com",
    "AES":   "https://investors.aes.com",
    "NRG":   "https://investors.nrgenergy.com",
    "AWK":   "https://ir.amwater.com",
    "LNT":   "https://investors.alliantenergy.com",
    "OGE":   "https://ir.oge.com",
    "NI":    "https://ir.nisource.com",
    "CNP":   "https://investors.centerpointenergy.com",
    "SRE":   "https://investors.sempra.com",
    "PEG":   "https://investor.pseg.com",
    "EQT":   "https://ir.eqt.com",
    # ── Real Estate (REITs) ──────────────────────────────────────────────────
    "AMT":   "https://ir.americantower.com",
    "PLD":   "https://ir.prologis.com",
    "EQIX":  "https://investor.equinix.com",
    "CCI":   "https://investor.crowncastle.com",
    "SPG":   "https://investors.simon.com",
    "O":     "https://www.realtyincome.com/investors",
    "VICI":  "https://investors.viciproperties.com",
    "EQR":   "https://equityapartments.com/investor-relations",
    "AVB":   "https://ir.avalonbay.com",
    "MAA":   "https://ir.maac.com",
    "WY":    "https://ir.weyerhaeuser.com",
    "CBRE":  "https://ir.cbre.com",
    "PSA":   "https://investors.publicstorage.com",
    "EXR":   "https://ir.extraspace.com",
    "WELL":  "https://ir.welltower.com",
    "VTR":   "https://ir.ventas.com",
    "ARE":   "https://ir.are.com",
    "BXP":   "https://ir.bxp.com",
    "KIM":   "https://investors.kimcorealty.com",
    "REG":   "https://regencycenters.com/investor-relations",
    "FRT":   "https://ir.federalrealty.com",
    "GLPI":  "https://ir.glpropinc.com",
    "SBAC":  "https://ir.sbasite.com",
    # ── Materials – Chemicals ────────────────────────────────────────────────
    "LIN":   "https://www.linde.com/investors",
    "APD":   "https://airproducts.com/investor-relations",
    "DD":    "https://dupont.com/investors",
    "DOW":   "https://investors.dow.com",
    "LYB":   "https://investors.lyondellbasell.com",
    "PPG":   "https://investor.ppg.com",
    "SHW":   "https://investors.sherwin-williams.com",
    "ECL":   "https://ir.ecolab.com",
    "IFF":   "https://ir.iff.com",
    "RPM":   "https://ir.rpminc.com",
    "ALB":   "https://investors.albemarle.com",
    "CE":    "https://investors.celanese.com",
    "HUN":   "https://ir.huntsman.com",
    "CC":    "https://investors.chemours.com",
    "OLN":   "https://www.olin.com/investor-relations",
    "WLK":   "https://ir.westlake.com",
    "EMN":   "https://investors.eastman.com",
    "ASH":   "https://ir.ashland.com",
    "AVNT":  "https://ir.avient.com",
    "GCP":   "https://ir.gcpat.com",
    # ── Materials – Metals & Mining ──────────────────────────────────────────
    "NEM":   "https://investor.newmont.com",
    "FCX":   "https://fcx.com/investors",
    "NUE":   "https://ir.nucor.com",
    "STLD":  "https://ir.steeldynamics.com",
    "X":     "https://investors.ussteel.com",
    "CLF":   "https://investors.clevelandcliffs.com",
    "AA":    "https://investors.alcoa.com",
    "RS":    "https://ir.rs.com",
    "CMC":   "https://ir.cmc.com",
    # ── Materials – Paper / Packaging ────────────────────────────────────────
    "IP":    "https://investor.internationalpaper.com",
    "PKG":   "https://ir.packagingcorp.com",
    "SEE":   "https://ir.sealedair.com",
    "AMCR":  "https://ir.amcor.com",
    "GPK":   "https://ir.graphicpkg.com",
    "SLGN":  "https://ir.silgan.com",
    "BALL":  "https://investor.ball.com",
    "CCK":   "https://ir.crowncork.com",
    "SON":   "https://ir.sonoco.com",
    # ── Materials – Construction ─────────────────────────────────────────────
    "VMC":   "https://ir.vulcanmaterials.com",
    "MLM":   "https://ir.martinmarietta.com",
    "SUM":   "https://ir.summitmaterials.com",
    "EXP":   "https://ir.usx.com",
    "USG":   "https://ir.usg.com",
    "BECN":  "https://ir.becn.com",
    # ── Food Service / Wholesale ─────────────────────────────────────────────
    "SYY":   "https://investors.sysco.com",
    "USFD":  "https://ir.usfoods.com",
    "PPC":   "https://ir.pilgrims.com",
    "SAFM":  "https://ir.sandersonfarms.com",
    # ── Berkshire – no earnings calls; shareholder letters only ────────────
    "BRK-B": "https://www.berkshirehathaway.com/reports.html",
    "BRK-A": "https://www.berkshirehathaway.com/reports.html",
    "BRK.B": "https://www.berkshirehathaway.com/reports.html",
    "BRK.A": "https://www.berkshirehathaway.com/reports.html",
    # ── Agriculture / Fertilizers ────────────────────────────────────────────
    "NTR":   "https://ir.nutrien.com",
    "MOS":   "https://www.mosaicco.com/investors",
    "CF":    "https://ir.cfindustries.com",
    "FMC":   "https://ir.fmc.com",
    "CTVA":  "https://ir.corteva.com",
    # ── Staffing / Business Services ─────────────────────────────────────────
    "MAN":   "https://manpowergroup.com/investors",
    "RHI":   "https://ir.roberthalf.com",
    "KELYA": "https://investor.kellyservices.com",
    # ── Misc / Diversified ───────────────────────────────────────────────────
    "GE":    "https://investors.ge.com",
    "MMM":   "https://investors.3m.com",
    "HON":   "https://investor.honeywell.com",
    "GPC":   "https://ir.genuineparts.com",
    "CARR":  "https://ir.carrier.com",
    "TDY":   "https://ir.teledyne.com",
    "HII":   "https://ir.huntingtoningalls.com",
    "DRS":   "https://ir.leonardodrs.com",
    "LDOS":  "https://investors.leidos.com",
    "BAH":   "https://investors.bah.com",
    "SAIC":  "https://ir.saic.com",
    "CACI":  "https://investor.caci.com",
    "EFX":   "https://investor.equifax.com",
    "TRU":   "https://ir.transunion.com",
    "NLSN":  "https://ir.nielsen.com",
    "IHS":   "https://ihsmarkit.com/investor-relations",
    "DNB":   "https://investor.dnb.com",
    "RRX":   "https://investors.rexnord.com",
    "WCC":   "https://ir.wesco.com",
    "HUBB":  "https://ir.hubbell.com",
    "GNRC":  "https://investors.generac.com",
    "NDSN":  "https://ir.nordson.com",
    "WTS":   "https://ir.watts.com",
    "ALLE":  "https://ir.allegion.com",
    "DOOR":  "https://ir.masterbrand.com",
    "AZEK":  "https://ir.azekco.com",
    "SWK":   "https://ir.stanleyblackanddecker.com",
    "FBHS":  "https://ir.fortunebrands.com",
    "MHK":   "https://ir.mohawkind.com",
    "WSO":   "https://ir.watsco.com",
    "AIT":   "https://ir.applied.com",
    "GATX":  "https://ir.gatx.com",
    "TRN":   "https://ir.trin.net",
    "WAB":   "https://ir.wabteccorp.com",
    "TKR":   "https://ir.timken.com",
    "RBC":   "https://rbc.bearings.com/investor-relations",
    # ── Media / Advertising ──────────────────────────────────────────────────
    "OMC":   "https://ir.omnicomgroup.com",
    "IPG":   "https://ir.interpublic.com",
    "PUB":   "https://www.publicisgroupe.com/en/investors",
    "WPP":   "https://www.wpp.com/investors",
    "TTD":   "https://investors.thetradedesk.com",
    "ZG":    "https://investors.zillowgroup.com",
    "Z":     "https://investors.zillowgroup.com",
    "RDFN":  "https://investors.redfin.com",
    "OPEN":  "https://investor.opendoor.com",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRANSCRIPT_SIGNALS = (
    "earnings call", "earnings-call", "conference call", "transcript",
    "q1", "q2", "q3", "q4", "quarterly results",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
}


def _is_transcript_url(url: str, title: str = "") -> bool:
    combined = (url + " " + title).lower()
    return any(sig in combined for sig in _TRANSCRIPT_SIGNALS)


def _normalise_filename(ticker: str, url: str, title: str = "", ext: str | None = None) -> str:
    """Derive a normalised filename from URL / title.

    ext overrides the file extension (e.g. '.txt' for scraped web pages).
    """
    # Try to extract quarter/year from title or URL
    quarter = "Q?"
    year = "????"
    q_match = re.search(r"\bq([1-4])\b", (title + " " + url).lower())
    y_match = re.search(r"\b(20\d{2})\b", title + " " + url)
    if q_match:
        quarter = f"Q{q_match.group(1)}"
    if y_match:
        year = y_match.group(1)

    # Try to keep the original filename if it's a PDF (and no ext override)
    if ext is None:
        parsed_u = urlparse(url)
        orig_name = Path(parsed_u.path).name
        if orig_name.lower().endswith(".pdf") and len(orig_name) > 5:
            if not orig_name.upper().startswith(ticker.upper()):
                return f"{ticker.upper()}_{orig_name}"
            return orig_name

    suffix = ext or ".pdf"
    label = "downloaded" if suffix == ".pdf" else "scraped"
    return f"{ticker.upper()}_EarningsCall_{quarter}_{year}_{label}{suffix}"


def _save_pdf(content: bytes, filename: str) -> Path:
    d = get_transcripts_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / filename
    dest.write_bytes(content)
    return dest


def _save_text(text: str, filename: str) -> Path:
    d = get_transcripts_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / filename
    dest.write_text(text, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

async def _try_download(url: str, timeout: int = 20) -> bytes | None:
    """Attempt to download a URL; return raw bytes or None."""
    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            follow_redirects=True,
            timeout=timeout,
            verify=get_ssl_verify(),  # use combined corporate CA bundle if available
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct or url.lower().endswith(".pdf"):
                    return resp.content
                # HTML page — look for PDF links
                if "html" in ct:
                    return None  # handled separately by _scrape_ir_page
    except Exception as e:
        logger.debug("Download failed for %s: %s", url, e)
    return None


# ---------------------------------------------------------------------------
# Strategy 1: Tavily web search
# ---------------------------------------------------------------------------

async def _search_tavily(
    ticker: str,
    company_name: str,
    quarter: str | None,
    year: int | None,
) -> list[dict[str, str]]:
    """Search Tavily for earnings call transcripts. Returns [{url, title}].

    Uses httpx directly (not the SDK) so we can disable SSL verification,
    which is required when running behind a corporate VPN with SSL inspection.
    """
    settings = get_settings()
    if not settings.tavily_api_key:
        logger.info("No Tavily key — skipping web search")
        return []

    period = ""
    if quarter and year:
        period = f"{quarter} {year} "
    elif year:
        period = f"{year} "

    queries = [
        f"{company_name} {period}earnings call transcript",
        f"{ticker} {period}earnings call transcript PDF",
        f"{company_name} {period}quarterly earnings conference call",
    ]

    seen: set[str] = set()
    results: list[dict[str, str]] = []

    async with httpx.AsyncClient(
        verify=get_ssl_verify(),
        timeout=30,
    ) as client:
        for q in queries:
            try:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": q,
                        "search_depth": "basic",
                        "max_results": 8,
                        "include_raw_content": False,
                    },
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    if url and url not in seen and _is_transcript_url(url, title):
                        seen.add(url)
                        results.append({"url": url, "title": title})
            except Exception as e:
                logger.warning("Tavily query failed: %s — %s", q, e)

    return results


# ---------------------------------------------------------------------------
# Strategy 2: Investor-relations page scraping
# ---------------------------------------------------------------------------

async def _scrape_ir_page(ticker: str) -> list[dict[str, str]]:
    """Scrape the known IR page for the ticker and look for PDF transcript links."""
    root = IR_ROOTS.get(ticker.upper())
    if not root:
        return []

    results: list[dict[str, str]] = []
    try:
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS, follow_redirects=True, timeout=15,
            verify=get_ssl_verify(),
        ) as client:
            resp = await client.get(root)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True)
            full_url = urljoin(root, href)
            if _is_transcript_url(full_url, text) and full_url not in {r["url"] for r in results}:
                results.append({"url": full_url, "title": text or full_url})

    except Exception as e:
        logger.warning("IR page scrape failed for %s: %s", ticker, e)

    return results


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------

class DiscoveryStep:
    def __init__(self, step: str, status: str, detail: str = ""):
        self.step = step
        self.status = status   # "running" | "done" | "error" | "skip"
        self.detail = detail

    def to_dict(self) -> dict:
        return {"step": self.step, "status": self.status, "detail": self.detail}


async def discover_and_download(
    ticker: str,
    company_name: str | None = None,
    quarter: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """
    Run the full discovery pipeline.
    Returns a result dict with downloaded files and status log.
    """
    name = company_name or ticker
    steps: list[dict] = []
    downloaded: list[dict] = []
    candidates: list[dict[str, str]] = []

    # ---- Step 1: Tavily search ----
    steps.append({"step": "web_search", "status": "running",
                  "detail": f"Searching web for '{name} earnings call transcript'..."})
    try:
        tavily_results = await _search_tavily(ticker, name, quarter, year)
        if tavily_results:
            candidates.extend(tavily_results)
            steps[-1].update({"status": "done",
                               "detail": f"Found {len(tavily_results)} candidate URLs via web search"})
        else:
            steps[-1].update({"status": "skip",
                               "detail": "No web search results (Tavily key not set or no matches)"})
    except Exception as e:
        steps[-1].update({"status": "error", "detail": str(e)})

    # ---- Step 2: IR page scrape ----
    steps.append({"step": "ir_scrape", "status": "running",
                  "detail": f"Checking investor relations page for {ticker}..."})
    try:
        ir_results = await _scrape_ir_page(ticker)
        if ir_results:
            # Deduplicate vs tavily results
            existing_urls = {c["url"] for c in candidates}
            new_ones = [r for r in ir_results if r["url"] not in existing_urls]
            candidates.extend(new_ones)
            steps[-1].update({"status": "done",
                               "detail": f"Found {len(ir_results)} links on IR page ({len(new_ones)} new)"})
        else:
            steps[-1].update({"status": "skip",
                               "detail": "No IR page configured or no transcript links found"})
    except Exception as e:
        steps[-1].update({"status": "error", "detail": str(e)})

    # ---- Step 3: Download PDFs ----
    steps.append({"step": "download", "status": "running",
                  "detail": f"Attempting to download {len(candidates)} candidates..."})

    transcripts_dir = get_transcripts_dir()
    existing = {f.name for f in transcripts_dir.iterdir() if f.exists()} if transcripts_dir.exists() else set()

    for candidate in candidates[:10]:   # cap at 10 attempts
        url = candidate["url"]
        title = candidate["title"]

        # Only attempt PDF URLs or known-good patterns
        if not (url.lower().endswith(".pdf") or "pdf" in url.lower()):
            # Skip HTML pages — they require deeper scraping
            logger.debug("Skipping non-PDF URL: %s", url)
            continue

        filename = _normalise_filename(ticker, url, title)
        if filename in existing:
            downloaded.append({
                "filename": filename,
                "url": url,
                "status": "already_exists",
            })
            continue

        content = await _try_download(url)
        if content and len(content) > 10_000:   # must be >10KB to be a real document
            try:
                _save_pdf(content, filename)
                downloaded.append({"filename": filename, "url": url, "status": "downloaded"})
                existing.add(filename)
                logger.info("Downloaded transcript: %s", filename)
            except Exception as e:
                downloaded.append({"filename": filename, "url": url, "status": f"save_error: {e}"})
        else:
            logger.debug("Could not download or too small: %s", url)

    new_downloads = [d for d in downloaded if d["status"] == "downloaded"]
    steps[-1].update({
        "status": "done" if new_downloads else "skip",
        "detail": (
            f"Downloaded {len(new_downloads)} new file(s)"
            if new_downloads
            else "No downloadable PDFs found automatically"
        ),
    })

    return {
        "ticker": ticker,
        "candidates_found": len(candidates),
        "candidates": candidates[:20],   # return for display
        "downloaded": downloaded,
        "steps": steps,
        "message": (
            f"Downloaded {len(new_downloads)} transcript(s)."
            if new_downloads
            else (
                f"Found {len(candidates)} candidate page(s) but none were directly downloadable PDFs. "
                "Try the URLs below or upload a file manually."
            )
        ),
    }

# ---------------------------------------------------------------------------
# Deep agent helpers
# ---------------------------------------------------------------------------

_DOC_TYPE_LABELS = (
    "earnings_call",
    "analyst_day",
    "investor_day",
    "press_release",
    "annual_report",
    "presentation",
    "other",
)


async def _classify_candidate(url: str, title: str) -> dict:
    """Ask the LLM to classify a candidate URL/title.

    Returns a dict with doc_type, quarter, year, confidence, reason.
    chat_json() is synchronous, so we offload it to a thread pool.
    """
    from app.services.llm_service import chat_json

    prompt = (
        "Classify this investor-relations document based on its URL and title.\n\n"
        f"Title: {title}\nURL: {url}\n\n"
        "Respond with valid JSON only:\n"
        '{"doc_type":"earnings_call|analyst_day|investor_day|press_release|annual_report|presentation|other",'
        '"quarter":"Q1|Q2|Q3|Q4|null","year":2024,"confidence":0.9,'
        '"reason":"one-sentence explanation"}'
    )
    try:
        result = await asyncio.to_thread(
            chat_json,
            [{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.0,
        )
        # Normalise
        result["doc_type"] = result.get("doc_type", "other")
        result["quarter"] = result.get("quarter") or None
        result["year"] = result.get("year") or None
        result["confidence"] = float(result.get("confidence", 0.5))
        result["reason"] = result.get("reason", "")
        return result
    except Exception as e:
        logger.debug("Classification failed for %s: %s", url, e)
        return {"doc_type": "other", "quarter": None, "year": None, "confidence": 0.0, "reason": ""}


# ---------------------------------------------------------------------------
# Webpage scraper — BS4 + optional LLM cleanup
# ---------------------------------------------------------------------------

# Tags that are almost never transcript content
_NOISE_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "noscript", "form", "button", "iframe", "figure", "picture",
]
# CSS class fragments that indicate non-content elements
_NOISE_CLASSES = ["nav", "menu", "banner", "cookie", "sidebar", "footer",
                  "header", "ad-", "ads-", "promo", "share", "social", "related"]


def _bs4_extract(html: str) -> str:
    """Strip HTML noise and return plain text via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_NOISE_TAGS):
            tag.decompose()
        for tag in soup.find_all(True):
            if tag is None or not hasattr(tag, "get"):
                continue
            cls = " ".join(tag.get("class", [])).lower()
            if any(x in cls for x in _NOISE_CLASSES):
                tag.decompose()
        raw = soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.warning("BS4 extraction failed: %s", e)
        return ""

    # Collapse consecutive blank lines to one
    lines = raw.splitlines()
    out: list[str] = []
    prev_blank = False
    for line in lines:
        s = line.strip()
        if not s:
            if not prev_blank:
                out.append("")
            prev_blank = True
        else:
            out.append(s)
            prev_blank = False
    return "\n".join(out).strip()


async def _tavily_extract(url: str) -> str | None:
    """Use Tavily's /extract endpoint to get content from JS-rendered pages."""
    settings = get_settings()
    if not settings.tavily_api_key:
        return None
    try:
        async with httpx.AsyncClient(verify=get_ssl_verify(), timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/extract",
                json={"api_key": settings.tavily_api_key, "urls": [url]},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                content = results[0].get("raw_content", "")
                if content and len(content) > 200:
                    return content
    except Exception as e:
        logger.debug("Tavily extract failed for %s: %s", url, e)
    return None


async def _llm_clean_transcript(text: str) -> str:
    """Ask the LLM to strip boilerplate from an already-extracted text block."""
    from app.services.llm_service import chat
    prompt = (
        "The following text was scraped from an investor-relations webpage. "
        "Extract ONLY the earnings call / conference call transcript content. "
        "Remove navigation, advertisements, cookie notices, share buttons, "
        "related-article links, and other boilerplate. "
        "Preserve all speaker names, titles, and their exact dialogue. "
        "If this page does NOT contain an earnings call transcript, "
        "reply with exactly: NOT_A_TRANSCRIPT\n\n"
        f"--- BEGIN ---\n{text[:12_000]}\n--- END ---"
    )
    result = await asyncio.to_thread(
        chat,
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=8000,
    )
    return result or ""


async def _scrape_webpage_text(url: str) -> str | None:
    """Fetch a webpage and return clean transcript text.

    Strategy:
      1. httpx + BS4 (fast, free, handles plain HTML)
      2. If result is too short → Tavily /extract (handles JS-rendered pages,
         anti-scraping, paywalls that Tavily can bypass)
      3. LLM cleanup pass on texts ≤ 5 000 words (remove residual boilerplate)
    """
    # 1. httpx + BS4
    text = ""
    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS, follow_redirects=True,
            timeout=30, verify=get_ssl_verify(),
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                text = _bs4_extract(resp.text)
            else:
                logger.debug("httpx got HTTP %s for %s", resp.status_code, url)
    except Exception as e:
        logger.info("httpx fetch failed for %s (%s) — trying Tavily extract", url, e)

    # 2. Tavily /extract fallback for JS-rendered / blocked pages
    if len(text) < 500:
        logger.info("BS4 result too short for %s, trying Tavily extract", url)
        tavily_text = await _tavily_extract(url)
        if tavily_text:
            text = tavily_text

    if len(text) < 200:
        logger.warning("Could not extract usable text from %s", url)
        return None

    # 3. LLM cleanup for short-enough texts
    word_count = len(text.split())
    if word_count <= 5_000:
        try:
            cleaned = await _llm_clean_transcript(text)
            if cleaned and "NOT_A_TRANSCRIPT" not in cleaned:
                return cleaned.strip()
        except Exception as e:
            logger.warning("LLM cleanup failed, using raw text: %s", e)

    return text


# ---------------------------------------------------------------------------
# Deep agent: streaming discovery
# ---------------------------------------------------------------------------

async def discover_stream(
    ticker: str,
    company_name: str | None = None,
    quarter: str | None = None,
    year: int | None = None,
) -> AsyncIterator[dict]:
    """Async generator: search → scrape → classify.  Yields SSE-ready dicts."""

    name = company_name or ticker
    settings = get_settings()
    seen: set[str] = set()
    all_raw: list[dict] = []

    period = ""
    if quarter and year:
        period = f"{quarter} {year} "
    elif year:
        period = f"{year} "

    tavily_queries = [
        f"{name} {period}earnings call transcript",
        f"{ticker} {period}earnings call transcript PDF",
        f"{name} {period}quarterly earnings conference call",
    ]

    # ── Step 1: Tavily ──────────────────────────────────────────────────────
    if settings.tavily_api_key:
        yield {"type": "step", "step": "web_search", "status": "running",
               "message": f"Searching web for '{name} earnings call'…"}
        tavily_count = 0
        try:
            async with httpx.AsyncClient(verify=get_ssl_verify(), timeout=30) as client:
                for q in tavily_queries:
                    try:
                        resp = await client.post(
                            "https://api.tavily.com/search",
                            json={
                                "api_key": settings.tavily_api_key,
                                "query": q,
                                "search_depth": "basic",
                                "max_results": 8,
                                "include_raw_content": False,
                            },
                        )
                        resp.raise_for_status()
                        for item in resp.json().get("results", []):
                            url = item.get("url", "")
                            title = item.get("title", "")
                            if url and url not in seen and _is_transcript_url(url, title):
                                seen.add(url)
                                c = {"url": url, "title": title, "source": "web"}
                                all_raw.append(c)
                                tavily_count += 1
                    except Exception as e:
                        logger.warning("Tavily query failed: %s — %s", q, e)
        except Exception as e:
            yield {"type": "step", "step": "web_search", "status": "error", "message": str(e)}
        else:
            yield {
                "type": "step", "step": "web_search",
                "status": "done" if tavily_count else "skip",
                "message": (f"Found {tavily_count} candidate(s) via web search"
                            if tavily_count else "No matches in web search"),
            }
    else:
        yield {"type": "step", "step": "web_search", "status": "skip",
               "message": "Tavily key not configured"}

    # ── Step 2: IR page scrape ──────────────────────────────────────────────
    if IR_ROOTS.get(ticker.upper()):
        yield {"type": "step", "step": "ir_scrape", "status": "running",
               "message": f"Checking {ticker} investor relations page…"}
        try:
            ir_results = await _scrape_ir_page(ticker)
            new_ones = [r for r in ir_results if r["url"] not in seen]
            for r in new_ones:
                seen.add(r["url"])
                c = {**r, "source": "ir_page"}
                all_raw.append(c)
            yield {
                "type": "step", "step": "ir_scrape",
                "status": "done" if new_ones else "skip",
                "message": (f"Found {len(new_ones)} additional link(s) on IR page"
                            if new_ones else "No new links on IR page"),
            }
        except Exception as e:
            yield {"type": "step", "step": "ir_scrape", "status": "error", "message": str(e)}
    else:
        yield {"type": "step", "step": "ir_scrape", "status": "skip",
               "message": f"No IR page configured for {ticker}"}

    # ── Step 3: Classify ────────────────────────────────────────────────────
    to_classify = all_raw[:12]
    if to_classify:
        yield {"type": "step", "step": "classify", "status": "running",
               "message": f"Classifying {len(to_classify)} candidate(s) with AI…"}
        for c in to_classify:
            try:
                cls = await _classify_candidate(c["url"], c["title"])
                yield {"type": "candidate", "data": {**c, **cls}}
            except Exception as e:
                logger.warning("Classification error: %s", e)
                yield {"type": "candidate", "data": {**c, "doc_type": "other",
                       "quarter": None, "year": None, "confidence": 0.0, "reason": ""}}
        yield {"type": "step", "step": "classify", "status": "done",
               "message": f"Classified {len(to_classify)} candidate(s)"}
    else:
        yield {"type": "step", "step": "classify", "status": "skip",
               "message": "No candidates to classify"}

    yield {"type": "done", "total": len(all_raw)}


# ---------------------------------------------------------------------------
# Deep agent: streaming download → save → parse
# ---------------------------------------------------------------------------

def _is_pdf_url(url: str) -> bool:
    """Heuristic: is this URL likely a direct PDF download?"""
    u = url.lower()
    return u.endswith(".pdf") or "/pdf" in u or "filetype=pdf" in u or "format=pdf" in u


async def process_stream(
    ticker: str,
    url: str,
    title: str,
) -> AsyncIterator[dict]:
    """Async generator: fetch transcript → save → parse preview.

    Handles two cases:
    - Direct PDF URL  → chunked binary download → save as .pdf
    - Webpage URL     → BS4 scrape + LLM cleanup → save as .txt

    The caller triggers analysis via the existing /analyze endpoint
    (the frontend does this automatically via onSelectFile).
    """
    from app.services.earnings_call_service import parse_transcript

    try:
        is_pdf = _is_pdf_url(url)

        if is_pdf:
            # ── PDF path ────────────────────────────────────────────────────
            filename = _normalise_filename(ticker, url, title)

            yield {"type": "step", "step": "download", "status": "running",
                   "message": f"Downloading PDF from {url[:70]}…"}

            chunks: list[bytes] = []
            total_bytes = 0

            try:
                async with httpx.AsyncClient(
                    headers=_BROWSER_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
                    verify=get_ssl_verify(),
                ) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code != 200:
                            yield {"type": "error",
                                   "message": f"Download failed: HTTP {resp.status_code}"}
                            return
                        content_length = int(resp.headers.get("content-length", 0))
                        async for chunk in resp.aiter_bytes(chunk_size=65_536):
                            chunks.append(chunk)
                            total_bytes += len(chunk)
                            yield {"type": "progress",
                                   "bytes_downloaded": total_bytes,
                                   "total_bytes": content_length or None}
            except Exception as e:
                yield {"type": "error", "message": f"Download error: {e}"}
                return

            content = b"".join(chunks)
            if len(content) < 10_000:
                yield {"type": "error",
                       "message": f"File too small ({len(content):,} bytes) — may not be a valid PDF."}
                return

            yield {"type": "step", "step": "download", "status": "done",
                   "message": f"Downloaded {len(content) / 1024:.0f} KB"}

            yield {"type": "step", "step": "save", "status": "running",
                   "message": f"Saving as {filename}…"}
            try:
                _save_pdf(content, filename)
                yield {"type": "step", "step": "save", "status": "done",
                       "message": f"Saved as {filename}"}
            except Exception as e:
                yield {"type": "error", "message": f"Save failed: {e}"}
                return

        else:
            # ── Web scrape path ─────────────────────────────────────────────
            filename = _normalise_filename(ticker, url, title, ext=".txt")

            yield {"type": "step", "step": "scrape", "status": "running",
                   "message": f"Scraping webpage {url[:70]}…"}

            text = await _scrape_webpage_text(url)
            if not text:
                yield {"type": "error",
                       "message": "Could not extract text from this page. "
                                  "It may require JavaScript or have anti-scraping protections."}
                return

            yield {"type": "step", "step": "scrape", "status": "done",
                   "message": f"Extracted {len(text.split()):,} words from page"}

            yield {"type": "step", "step": "save", "status": "running",
                   "message": f"Saving as {filename}…"}
            try:
                _save_text(text, filename)
                yield {"type": "step", "step": "save", "status": "done",
                       "message": f"Saved as {filename}"}
            except Exception as e:
                yield {"type": "error", "message": f"Save failed: {e}"}
                return

        # ── Parse preview (shared) ──────────────────────────────────────────
        yield {"type": "step", "step": "parse", "status": "running",
               "message": "Extracting text and sections…"}
        try:
            parsed = await asyncio.to_thread(parse_transcript, filename)
            wc = parsed["meta"].get("word_count", 0)
            sc = len(parsed.get("sections", []))
            yield {"type": "step", "step": "parse", "status": "done",
                   "message": f"Parsed {wc:,} words across {sc} sections"}
        except Exception as e:
            yield {"type": "step", "step": "parse", "status": "error",
                   "message": f"Parse preview failed: {e}"}

        yield {"type": "complete", "filename": filename}

    except Exception as e:
        logger.error("process_stream error: %s", e)
        yield {"type": "error", "message": str(e)}
