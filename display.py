import os
import configparser
import socket
import pygame
from pygame.locals import *
from messages import *
import screeninfo
import string
import logging
from logging.handlers import TimedRotatingFileHandler
import qrcode

UDP_CONTROLLER = ("0.0.0.0", 1773)
UDP_DRIVER = ("0.0.0.0", 1776)
udp_controller = None
udp_driver = None


LOG_LEVELS = {'DEBUG':    logging.DEBUG,
              'INFO':     logging.INFO,
              'WARNING':  logging.WARNING,
              'ERROR':    logging.ERROR,
              'CRITICAL': logging.CRITICAL
              }


cdgi_logger = logging.getLogger('cgde19')


def try_and_log(msg):
    """
    Декоратор выполняет метод класса.
    Класс должен содержать параметр logger
    При возникновения исключения выводит в лог два сообщения
    с текстом, который передается в декоратор как аргумент,
    и с текстом исключения.

    Возвращает кортеж из двух элементов:
    Если было исключение - None и описание ошибки msg;
    если не было - объект, возвращаемый методом, и 'OK'
    Args:
        msg (str): текст выводимый в лог при возникновении исключения
    """

    def dcrtr(func):
        def wrap(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs), 'OK'
            except Exception as ex:
                dtl_msg = "{}: {}".format(msg, ex)
                self.logger.error(dtl_msg)
                return None, dtl_msg
        return wrap
    return dcrtr


def result(res):
    """
    Извлекает результат выполнения функции из кортежа, созданного декоратором try_and_log.
    Если выполнение функции не было успешным, генерирует исключение.
    Args:
        res (tuple): кортеж, возвращаемый декоратором try_and_log
    Raises:
        Exception: Исключение обработанное декориратором try_and_log
    Returns:
        Any: Результат возвращаемый декорируемой функцией
    """
    if res[1] != 'OK':
        raise Exception(res[1])
    return res[0]


class Config:
    default_config = {'ScreenSize': 'auto',
                      'FullScreen': '1',
                      'BackgroundFile': '',
                      'BackgroundFileAlarm': '',
                      'BackgroundFilePass': '',
                      'BackgroundColor': "0064FF",
                      'BackgroundColorAlarm': 'cc3333',
                      'BackgroundColorPass': '008833',
                      'Font': "",
                      'FontSize': "auto",
                      'FontColor': "yellow",
                      'LogLevel': "INFO"
                      }

    def __init__(self, file_name, logger):
        self.logger = logger
        self.cfg = configparser.ConfigParser()
        # noinspection PyBroadException
        try:
            self.cfg.read(file_name)
        except Exception:
            return

        self.config = dict(self.default_config)

        monitors = screeninfo.get_monitors()
        self.def_w = monitors[0].width
        self.def_h = monitors[0].height

        for key in self.config:
            # noinspection PyBroadException
            try:
                self.config[key] = self.cfg['DEFAULT'][key]
            except Exception:
                continue

    @staticmethod
    def get_color(color_string):
        if set(color_string) < set(string.hexdigits):
            return pygame.Color("0x" + color_string)
        else:
            return pygame.Color(color_string)

    @property
    def screen_size(self):
        # noinspection PyBroadException
        try:
            return tuple(map(int, self.config['ScreenSize'].split(',')))[:2]
        except Exception:
            return self.def_w, self.def_h

    @property
    def full_screen(self):
        # noinspection PyBroadException
        try:
            return int(self.config['FullScreen'])
        except Exception:
            return self.default_config['FullScreen']

    def background_file(self, msg_type):
        file_name = ['BackgroundFile', 'BackgroundFileAlarm', 'BackgroundFilePass']
        try:
            f = open(self.config[file_name[msg_type]])
            f.close()
            return self.config[file_name[msg_type]]
        except OSError:
            return self.default_config[file_name[msg_type]]

    def background_color(self, msg_type):
        colors = ['BackgroundColor', 'BackgroundColorAlarm', 'BackgroundColorPass']
        try:
            return self.get_color(self.config[colors[msg_type]])
        except ValueError:
            return self.get_color(self.default_config[colors[msg_type]])

    @property
    def font(self):
        try:
            f = open(self.config['Font'])
            f.close()
            return self.config['Font']
        except OSError:
            return self.default_config['Font']

    @property
    def font_size(self):
        # noinspection PyBroadException
        try:
            return int(self.config['FontSize'])
        except Exception:
            f = pygame.font.Font(self.font, 50)
            w = f.render('Ж' * 20, True, self.font_color).get_size()[0]
            return int(0.98 * 50 * self.screen_size[0] / w)

    @property
    def font_color(self):
        try:
            return self.get_color(self.config['FontColor'])
        except ValueError:
            return self.get_color(self.default_config['FontColor'])

    @property
    def log_level(self):
        try:
            level = self.config['LogLevel']
        except ValueError:
            level = self.default_config['LogLevel']
        if level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            return  LOG_LEVELS['INFO']
        return LOG_LEVELS[level]


class Display:
    def __init__(self, cfg_fname, logger = None):
        if logger is None:
            self.logger = logging.getLogger('cgde19')
        else:
            self.logger = logger
        if not os.path.isdir("Logs"):
            os.mkdir("Logs")
        self.logger_handler = TimedRotatingFileHandler('Logs/cgde.log', when='midnight', backupCount=30)
        self.logger.addHandler(self.logger_handler)
        self.logger.setLevel(logging.INFO)
        self.logger.info("\n****************************************************\n")
        self.logger_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s]:  %(message)s'))
        self.logger.info("Start display CDGE-19")
        self.cfg = Config(cfg_fname, self.logger)
        self.logger.setLevel(self.cfg.log_level)
        self.prev_msg = (None, None, None)
        self.con = False
        self.con_cnt = False
        self.receipt = False
        self.qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,
                                box_size=10,
                                border=2,
                                )
        self.qr_size = 200

        pygame.display.init()
        self.fps = 30
        if self.cfg.full_screen:
            self.screen = pygame.display.set_mode(self.cfg.screen_size, pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.cfg.screen_size)
        pygame.mouse.set_visible(False)

        self.background = [None, None, None]
        for i in range(len(self.background)):
            if self.cfg.background_file(i):
                self.background[i] = pygame.image.load(self.cfg.background_file(i))
                self.logger.info("Background file {}: '{}'".format(i + 1, self.cfg.background_file(i)))
            elif self.cfg.background_file(MSG_TYPE_GENERAL):
                self.background[i] = pygame.image.load(self.cfg.background_file(MSG_TYPE_GENERAL))
                self.logger.info("Background file {}: '{}'".format(i + 1,
                                                                   self.cfg.background_file(MSG_TYPE_GENERAL)))
            else:
                self.background[i] = pygame.transform.scale(self.screen, self.cfg.screen_size)
                self.background[i].fill(self.cfg.background_color(i))
                self.logger.info("Background colour {}: {}".format(i + 1, self.cfg.background_color(i)))

        # Подгонка размеров фонового изображения под разрешение экрана
        for i in range(len(self.background)):
            bg_w = self.background[i].get_size()[0]
            bg_h = self.background[i].get_size()[1]
            if self.cfg.screen_size[0] / bg_w >= self.cfg.screen_size[1] / bg_h:
                bg_h *= self.cfg.screen_size[0] / bg_w
                temp_serfice = pygame.transform.scale(self.background[i], (self.cfg.screen_size[0], bg_h))
                crop = (0, (bg_h - self.cfg.screen_size[1]) // 2, self.cfg.screen_size[0], self.cfg.screen_size[1])
                self.background[i].blit(temp_serfice, (0, 0), crop)
            else:
                bg_w *= self.cfg.screen_size[1] / bg_h
                temp_serfice = pygame.transform.scale(self.background[i], (bg_w, self.cfg.screen_size[1]))
                crop = ((bg_w - self.cfg.screen_size[0]) // 2, 0, self.cfg.screen_size[0], self.cfg.screen_size[1])
                self.background[i].blit(temp_serfice, (0, 0), crop)

        pygame.font.init()
        if self.cfg.font:
            self.font = pygame.font.Font(self.cfg.font, self.cfg.font_size)
            font_name = self.cfg.font
        else:
            self.font = pygame.font.SysFont('courier new', self.cfg.font_size)
            font_name = 'courier new'
        self.logger.info('Font: ' + font_name)
        # self.font.set_bold(True)
        # self.font.set_italic(True)
        self.load_icons()
        self.display_message(0, [])
        self.shutdown = False

    @try_and_log('Error: Display.run()')
    def run(self):
        self.udp_server_init()
        clock = pygame.time.Clock()
        while not self.shutdown:
            self.display_poll()
            self.udp_server_poll()
            clock.tick(self.fps)
        self.udp_server_quit()
        pygame.quit()

    @try_and_log('Error: Display.display_poll()')
    def display_poll(self):
        for event in pygame.event.get():
            if event.type == KEYDOWN:
                self.logger.debug("Key down: {}".format(event.key))
                if event.key == K_F12:
                    self.shutdown = True
            elif event.type == QUIT:
                self.logger.debug("pygame.event: {}".format(event.type))
                self.shutdown = True

    @try_and_log('Error: Display.render_text()')
    def render_text(self, txt, y):
        t = self.font.render(txt, True, self.cfg.font_color)
        x = (self.cfg.screen_size[0] - t.get_size()[0]) // 2
        self.screen.blit(t, (x, y))

    @try_and_log('Error: Display.display_message()')
    def display_message(self, msg_code, msg_params):
        lines, icon, msg_type = list(MESSAGES.get(msg_code, MESSAGES[0]))

        self.screen.blit(self.background[msg_type], (0, 0))

        h = self.font.render('TXT', True, self.cfg.font_color).get_size()[1]

        lines_copy = lines.copy()
        msg = lines_copy, icon, msg_type

        self.receipt = False
        if icon is not None:
            icon_file = "icons/{0}".format(icon)
            if os.path.isfile(icon_file):
                icon = pygame.image.load(icon_file).convert_alpha()
                if "receipt.png" in icon_file:
                    self.receipt = True

        if self.receipt:
            lines_copy.append("Электронный чек:")
            lines_copy.append("")
            lines_copy.append("")

        n = len(lines_copy) if msg_code < 255 else len(msg_params)

        if self.prev_msg != msg:
            msg_text = []
            for i in range(n):
                msg_text.append(lines_copy[i].format(*msg_params))
            self.logger.debug("Message: " + ' | '.join(msg_text))
            self.prev_msg = msg
            if not self.receipt:
                # Если сообщение сменилось и в нем нет электронного чека, удаляем файл с чеком
                if os.path.isfile("icons/receipt.png"):
                    os.remove("icons/receipt.png")

        for i in range(n):
            y = (i + 1) * (self.cfg.screen_size[1] - n * h) / (n + 1) + i * h
            self.render_text(lines_copy[i].format(*msg_params), y)

        if self.receipt:
            self.screen.blit(icon, (self.cfg.screen_size[0] / 2 - self.qr_size / 2, self.cfg.screen_size[1] / 1.9))

        pygame.display.flip()

    @try_and_log('Error: Display.load_icons()')
    def load_icons(self):
        for n in MESSAGES.keys():
            # noinspection PyBroadException
            try:
                MESSAGES[n][1] = pygame.image.load("icons/{}.png".format(n))
                self.logger.info("The icon file 'icons/{}.png' is uploaded".format(n) )
            except Exception:
                pass

    @try_and_log('Error: udp_server_init()')
    def udp_server_init(self):
        global udp_controller, udp_driver
        udp_controller = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_controller.bind(UDP_CONTROLLER)
        udp_controller.settimeout(0.1)
        udp_driver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_driver.bind(UDP_DRIVER)
        udp_driver.settimeout(0.1)


    @try_and_log('Error: udp_server_quit()')
    def udp_server_quit(self):
        if isinstance(udp_controller, socket.socket):
            udp_controller.close()
        if isinstance(udp_driver, socket.socket):
            udp_driver.close()


    @try_and_log('Error: udp_server_poll()')
    def udp_server_poll(self):
        if isinstance(udp_controller, socket.socket):
            # noinspection PyBroadException
            try:
                data, addr = udp_controller.recvfrom(1024)
                if data:
                    self.parse_udp_data(data)
                    if not self.con:
                        self.logger.info("Connection established: address - {}, potr - {}".format(addr[0], addr[1]))
                    self.con = True
                    self.con_cnt = 0
            except socket.timeout:
                if self.con:
                    self.con_cnt += 1
                if self.con_cnt > 100:
                    self.logger.info("Connection lost")
                    self.con = False
                    self.con_cnt = 0

        if isinstance(udp_driver, socket.socket):
            # noinspection PyBroadException
            try:
                data, addr = udp_driver.recvfrom(1024)
                if data:
                    self.parse_udp_data(data)
                    if not self.con:
                        self.logger.info("Connection established: address - {}, potr - {}".format(addr[0], addr[1]))
                    self.con = True
                    self.con_cnt = 0
            except socket.timeout:
                pass

    @try_and_log('Error: parse_udp_data()')
    def parse_udp_data(self, data):
        com_code = to_int(data[2])
        com_params = data[3:-1]
        self.parse_command(com_code, com_params)


    @try_and_log('Error: parse_msg_params()')
    def parse_msg_params(self, mp):
        msg_params = []
        while mp:
            s_len = to_int(mp[0])
            if s_len == 0:
                break
            s = mp[1:s_len + 1].decode("cp1251")
            msg_params.append(s)
            mp = mp[s_len + 1:]
        return msg_params


    @try_and_log('Error: parse_command()')
    def parse_command(self, com_code, com_params):
        if com_code == 1:
            msg_code = to_int(com_params[0])
            msg_params = result(self.parse_msg_params(com_params[3:]))
            display.display_message(msg_code, msg_params)
            if msg_code != 255:
                while len(msg_params) < 4:
                    msg_params.append("")
        elif com_code == 5:
            self.parse_receipt(com_params)
        else:
            pass

    @try_and_log('Error: parse_receipt()')
    def parse_receipt(self, data):
        self.qr.clear()
        self.qr.add_data(data)
        self.qr.make(fit=True)

        img = self.qr.make_image(fill_color="black", back_color="yellow")
        self.qr_size = int(self.cfg.screen_size[1] / 2.5)
        img = img.resize((self.qr_size, self.qr_size))
        img.save("icons/receipt.png")


def to_int(c):
    if type(c) == str:
        return ord(c)
    elif type(c) == int:
        return c
    else:
        return 0




if __name__ == "__main__":
    display = Display('cgde.ini', cdgi_logger)
    display.run()
