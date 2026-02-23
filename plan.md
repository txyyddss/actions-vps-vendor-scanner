# Development requirements

## Requirements

You need to develop a product scanner and stock monitor via github actions. Read through all the requirements and find the way that best implement the features. You should add code comments. Prioritize the accuracy also the code efficiency. You should keep the code and folder clean and organized. Make the best of github and python, avoid unecessary codes. Think and plan carefully to find the best approach. You should make sure web content get by the crawler is fully english (just make your best, do not drop non-english contents). Apply multi-thread logic to improve efficiency of run. Everything should be the latest version. To increase performance, flaresoverr, socks5 proxy and browser simulation must be used for fallback or used in necessary special case.

## Structure

### Folders and files

The indentation shows the expected layer of folders and files. You are not required to follow exactly the same. Just for guidience.

- Other files
- .github
    - Issue templates
    - Action files
    - other github stuff
- config
  - config.json
  - sites.json
- src
  - hidden scanner
    - WHMCS
      - python files
    - Hostbill
      - python files
  - discoverer
    - python files
  - parsers
    - python files
  - miscellaneous
    - python files of http client, telegram message sender, web dashboard generator, etc.
  - site specific crawler
    - python files of sites require customized crawler
  - others
    - other python files
  - main python files
- data
  - products.json
  - stock.json
- docs
  - .md files of detailed technical stuff and explanation of each module
- web
  - for generated static web page
- debug
  - python files for debugging or testing
  - python files for local standalone crawler for understanding the site structure
- requirements.txt
- pyproject.toml
- README.md
### Structure of config files

#### sites.json
```json
{
  "sites": {
    "site": [
      {
        "enabled" : true,
        "name": "xxx",
        "url": "https://example.com",
        "discoverer" : true,
        "category": "WHMCS",
        "special crawler" : "",
        "product scanner": true,
        "category scanner" : true
      }
    ]
  }
}
```

#### config.json
For configuration. You can determain on your own needs.

### Github Actions

#### Scanner

Run per 12 hours

Paralleal jobs
- Product scanner
- Category scanner
- Discoverer
After the paralleral jobs finish, create a job that combine, wash data and send notifications

#### Stock Alert

Run per 15 minutes

Read from products.json, scan through all the product and check its availability and send notification

#### Issue Processor

Run when new issue is opened

- For site edit/add/delete request, process it automatically and send telegram notifications
- For feature request / bug report, just send telegram notifications.

### Pull request processor

Run when new pull request is opened

- Run test and leave a comment for the pull request
- Automatically approve if 100% suitable

## Goal

Integrate flaresoverr and socks5 support. Make sure failures are safe and automatically retry. Wait for some time if meets rate limit. Output detailed console logs. 

### Valid examples

Some of the sites applied custom themes or uses different version of WHMCS. You should make sure the crawler can get the data correctly despite the difference. You should analyze:
- Html code
- Where the product name is
- Where the price is
- How to determine whether is is out of stock or not
- Where the description is
- Behaviors
- Where the location choices is (Some of the sites)

#### Categories - WHMCS


https://app.vmiss.com/store/cn-hk-bgp-v3
https://app.kaze.network/index.php?rp=/store/hkg3-fttx
https://www.bagevm.com/index.php?rp=/store/los-angeles-servers
https://my.frantech.ca/cart.php?gid=45

#### Categories - Hostbill

https://clientarea.gigsgigscloud.com/cart/sg--standard-route/
https://clientarea.gigsgigscloud.com/cart/philippines-manila-simplecloud/
https://clients.zgovps.com/index.php?/cart/tokyo-intel-vps/
https://clients.zgovps.com/index.php?/cart/osaka-amd-ryzen9-performance-vps/
https://clientarea.gigsgigscloud.com/?cmd=cart&cat_id=3

#### Products - WHMCS

It usually redirects to pages like:
- https://xxx/cart.php?a=confproduct&i=

It do not redirect when the product is out of stock. 

##### In stock

https://app.vmiss.com/store/cn-hk-bgp-v3/pro
https://app.kaze.network/index.php?rp=/store/hkg1-fttx/hkt-1000
https://backwaves.net/cart.php?a=add&pid=2&billingcycle=monthly
https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/12gb-ram
https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmaz-3
https://my.racknerd.com/index.php?rp=/store/new-year-specials/1-gb-kvm-vps-new-year-special


##### Out of stock

https://app.kaze.network/index.php?rp=/store/hkg2-ftth/hkt-1500-dedicated-ip
https://cloud.colocrossing.com/index.php?rp=/store/specials/black-friday-flash-offer-4gb-ram-vps-2025-1
https://backwaves.net/store/tkyiijshare/tkyprimeshare01
https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsjcvf-1
https://my.racknerd.com/index.php?rp=/store/seo-dedicated-servers/dual-xeon-l5520-los-angeles-dc-01

#### Products - Hostbill

It seems to approve multiple formats. Its shows pop out message when a product is out of stock. It seems to use js sscript to present out of stock messages instead of showing it on the page. Please analyze.

##### In stock

https://clientarea.gigsgigscloud.com/cart/sg--standard-route/?id=479
https://clientarea.gigsgigscloud.com/cart/sg--standard-route/&action=add&id=479
https://clientarea.gigsgigscloud.com/cart/&action=add&id=479
https://clients.zgovps.com/index.php?/cart/special-offer/&action=add&id=122&cycle=a
https://clients.zgovps.com/index.php?/cart/&action=add&id=122

##### Out of Stock

https://clientarea.gigsgigscloud.com/cart/us--premium-china-with-ddos-protection/?id=354
https://clientarea.gigsgigscloud.com/cart/&action=add&id=354
https://clients.zgovps.com/index.php?/cart/special-offer/&action=add&id=94&cycle=a
https://clients.zgovps.com/index.php?/cart/&action=add&id=94

### Get product data
You should get product name, Price, Cycles, product details, and locations and output it into products.json in a clean and structured json format. Do not cut long product details, just keep it the same as the website.
#### Discoverer
Heuristicly discover all the links in the html source code and visit the link and discover all the links in the html source code and repeat until no new pages are found.
After that, extract products from category page and product page.
#### Scanner

##### Gid scanner - WHMCS
Applicapable for all the WHMCS sites. It redirects to default category page when the gid is invalid, and redirects to different category page if the link is valid. You need stop when there's some duplicate pages (or final url) of different consecutive gids. Scan from gid=0 and each time +1.
https://xxx/cart.php?gid=
##### Pid scanner - WHMCS
Applicapable for all the WHMCS sites. Start from pid=0 and each time +1. It redirects to default category page when the pid is invalid, and redirects to confproduct if the product is in stock. If it is out of stock, it will be either no redirect or redirect to the product page with english like "/store/us-los-angeles-bgp/basic". You need stop when there's some duplicate pages (or final url) of different consecutive pids.
https://xxx/cart.php?a=add&pid=
#### CatID scanner - Hostbill
Applicapable for all Hostbill sites. Start from 0 and each time +1. It shows the category page if the cat_id is valid, otherwise there will be "No services yet" presented on the site. You need to stop if there are some "No services yet" presented on different consecutive cat_ids. 
https://xxx/?cmd=cart&cat_id=
#### Pid scanner - Hostbill
Applicapable for all Hostbill sites. Start from 0 and each time +1. It shows "No services yet" if the id is invalid, and shows the product information or the category if it is valid.
https://xxx/index.php?/cart/&action=add&id=

#### Data merging
You should use urls to merge datas. If there are conflict, follow Discoverer > Product Scanner > Category Scanner. Wash invalid urls like https://console.po0.com/contact.php. Only include single product names. Send telegram message if there are new products or products being deleted. You should send tg messages afterwards about the statistic of this run. Delete an regenerate products.json after sending telegram message.

### Stock Alert
Read products.json and get the stock info and write the data into stock.json. Send telegram message if there are restocks. Delete an regenerate stock.json after sending telegram message.

### Issue Processor
Process issue of site edit/add/delete. Automatically read the issue form and edit sites.json. Automatically close and mark the issue as not planned if the issue form is invalid.

## Issue Forms
You should generate template issue forms that best fits the functions.

## Telegram message requirements
* **Visual Structure:** Use bold headers for the main title and sub-sections to create a clear hierarchy.
* **Formatting:** Use `**bold**` for emphasis, `__italics__` for nuance, and `> blockquotes` for key takeaways or quotes.
* **Emoji Aesthetic:** Use emojis as bullet points or to highlight key emotions, but keep it tasteful—avoid 'emoji soup.'
* **The Hook:** Start with a high-impact first line that stops the scroll.
* **Readability:** Keep paragraphs extremely short (2-3 sentences max) and use plenty of white space.
* **Call to Action (CTA):** End with a clear, bolded instruction or a question to encourage comments.
* **The Content:** [INSERT YOUR TOPIC OR RAW TEXT HERE]
* **Tone:** [E.g., Hype/Professional/Minimalist/Witty]"

## Dashboard generation
Aggregate Buying Dashboard
Output: static web files.

Design: Futuristic, "Cyberpunk" or "High-Tech" aesthetic. Dark mode by default and light mode optional.

Features:

Sortable table or grid view of all monitored products.

Status indicators (Green for Stock, Red for OOS).

"Buy Now" buttons.

Last updated timestamp.

Responsiveness: Must be mobile-friendly.

Show statistics.

## Preset Domains
You should edit some of the sites by your self.
{
  "sites": {
    "site": [
      {
        "enabled": true,
        "name": "RFCHOST",
        "url": "https://my.rfchost.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "VMISS",
        "url": "https://app.vmiss.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category": "WHMCS",
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "ACCK",
        "url": "https://acck.io/",
        "discoverer": false,
        "category": "",
        "special crawler": "You should fill in this squad",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "PortChannel Zero",
        "url": "https://console.po0.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "Akile",
        "url": "https://akile.io/",
        "discoverer": false,
        "category": "",
        "special crawler": "You should fill in this squad",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "GreenCloud",
        "url": "https://greencloudvps.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "Kaze Network Limited",
        "url": "https://app.kaze.network/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "NMCloud",
        "url": "https://nmcloud.cc/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "Frantech",
        "url": "https://my.frantech.ca/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "Backwaves",
        "url": "https://backwaves.net/",
        "discoverer": true,
        "category": "",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "GGVision",
        "url": "https://cloud.ggvision.net/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "WAP.ac",
        "url": "https://wap.ac/",
        "discoverer": true,
        "category": "",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "BageVM",
        "url": "https://www.bagevm.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "ColoCrossing",
        "url": "https://cloud.colocrossing.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "DMIT",
        "url": "https://www.dmit.io/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "ZgoVPS",
        "url": "https://clients.zgovps.com/",
        "discoverer": true,
        "category": "HostBill",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "RackNerd",
        "url": "https://my.racknerd.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": false,
        "category scanner": false
      },
      {
        "enabled": true,
        "name": "GigsGigsCloud",
        "url": "https://clientarea.gigsgigscloud.com/",
        "discoverer": true,
        "category": "HostBill",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "Boil Network",
        "url": "https://cloud.boil.network/",
        "discoverer": true,
        "category": "",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "BFFYun",
        "url": "https://cloud.bffyun.com/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      },
      {
        "enabled": true,
        "name": "BestVM",
        "url": "https://bestvm.cloud/",
        "discoverer": true,
        "category": "WHMCS",
        "special crawler": "",
        "product scanner": true,
        "category scanner": true
      }
    ]
  }
}

## Speacial sites
acck.io and akile.io are neither hostbill nor WHMCS. They have apis of listing products.
https://api.akile.io/api/v1/store/GetVpsStoreV3
https://api.acck.io/api/v1/store/GetVpsStore
Example product link:
https://acck.io/shop/server?type=traffic&areaId=1&nodeId=9&planId=78
https://acck.io/shop/server?type=bandwidth&areaId=2&nodeId=12&planId=99
https://akile.io/shop/server?type=traffic&areaId=2&nodeId=23&planId=934
https://akile.io/shop/server?type=bandwidth&areaId=5&nodeId=9&planId=904

## Instruction of testing-improvements
1. Run tests locally
2. Read stock.json and products.json
3. Read the static web dashboard content
4. Analyze the results to find out things to imorove
5. Edit the codes

Local flaresoverr(ver.3.4.6) url for testing http://127.0.0.1:8191/

You should analyze all the sites locally before starting to write implementation plan.


