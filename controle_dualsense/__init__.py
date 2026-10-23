"""Controle DualSense USB opcional para o Vigia (mudanca controle-dualsense-vigia).

Importar este pacote NAO abre HID, camera, COM, rede, janela nem banco.
O modulo HID real (`hid`, do pacote hidapi) so e importado por
adaptador_hid.AdaptadorHID quando o recurso e habilitado.
"""
