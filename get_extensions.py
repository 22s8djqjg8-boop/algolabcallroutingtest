# -*- coding: utf-8 -*-
"""
TelServer 내선 로그인 정보 조회 스크립트
GetTelServer070R SOAP 웹서비스 호출
"""
import http.client
import xml.etree.ElementTree as ET
import html

SOAP_BODY = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetTelServer070R xmlns="NS_TelReject">
      <sDiv>QUICK</sDiv>
      <Div_DB>DB2</Div_DB>
      <sKindOfDrive>QUICK</sKindOfDrive>
      <CcCode>9055</CcCode>
    </GetTelServer070R>
  </soap:Body>
</soap:Envelope>'''

def main():
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': '"NS_TelReject/GetTelServer070R"',
    }

    print("=" * 60)
    print("  TelServer 내선 로그인 정보 조회")
    print("  서버: food.282.co.kr")
    print("  CcCode: 9055 (알고퀵)")
    print("=" * 60)
    print()

    try:
        conn = http.client.HTTPConnection("food.282.co.kr", timeout=15)
        conn.request("POST", "/WSTelReject/Service.asmx", SOAP_BODY.encode('utf-8'), headers)
        response = conn.getresponse()
        data = response.read().decode('utf-8', errors='replace')
        conn.close()

        print(f"HTTP 상태: {response.status} {response.reason}")
        print()

        if response.status != 200:
            print("요청 실패. 응답 내용:")
            print(data[:2000])
            return

        # SOAP 응답에서 결과 추출
        ns = {
            'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
            'ns': 'NS_TelReject'
        }
        root = ET.fromstring(data)
        result_elem = root.find('.//ns:GetTelServer070RResult', ns)

        if result_elem is None or not result_elem.text:
            print("결과가 비어있습니다.")
            print("원본 응답:")
            print(data[:3000])
            return

        result_xml = html.unescape(result_elem.text)
        print("--- 원본 응답 XML ---")
        print(result_xml[:5000])
        print()

        # 내부 XML 파싱 시도
        try:
            inner_root = ET.fromstring(result_xml)
            print("--- 파싱된 내선 정보 ---")
            for i, elem in enumerate(inner_root):
                print(f"\n[{i+1}] {elem.tag}")
                for child in elem:
                    print(f"    {child.tag}: {child.text}")
        except ET.ParseError:
            print("(내부 XML 파싱 실패 - 위 원본 데이터를 확인하세요)")

    except Exception as e:
        print(f"오류 발생: {e}")
        print()
        print("해결 방법:")
        print("1. food.282.co.kr 서버에 접근 가능한지 확인")
        print("2. 방화벽에서 80포트 허용 여부 확인")
        print("3. ping food.282.co.kr 으로 연결 테스트")

    # 추가: GetTelServer070R_New 도 시도
    print()
    print("=" * 60)
    print("  GetTelServer070R_New 도 시도합니다...")
    print("=" * 60)

    soap_new = SOAP_BODY.replace("GetTelServer070R", "GetTelServer070R_New")
    headers_new = dict(headers)
    headers_new['SOAPAction'] = '"NS_TelReject/GetTelServer070R_New"'

    try:
        conn = http.client.HTTPConnection("food.282.co.kr", timeout=15)
        conn.request("POST", "/WSTelReject/Service.asmx", soap_new.encode('utf-8'), headers_new)
        response = conn.getresponse()
        data = response.read().decode('utf-8', errors='replace')
        conn.close()

        print(f"HTTP 상태: {response.status} {response.reason}")

        if response.status == 200:
            root = ET.fromstring(data)
            result_elem = root.find('.//{NS_TelReject}GetTelServer070R_NewResult')
            if result_elem is None:
                # namespace 없이 재시도
                for elem in root.iter():
                    if 'Result' in elem.tag and elem.text:
                        result_xml = html.unescape(elem.text)
                        print()
                        print("--- 원본 응답 XML ---")
                        print(result_xml[:5000])
                        break
                else:
                    print("원본 응답:")
                    print(data[:3000])
        else:
            print(data[:2000])

    except Exception as e:
        print(f"오류: {e}")

if __name__ == "__main__":
    main()
    input("\n아무 키나 눌러 종료...")
