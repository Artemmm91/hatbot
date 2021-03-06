import _thread
import random
import time
import os
import vk_api
from keyboards import *
from messages_rus import *
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
from word_bank import words_easy, words_medium, words_hard

from decorators import admin_required


class Bot:
    def __init__(self):
        self.vk_session = vk_api.VkApi(token=os.environ['token_id'])
        self.long_poll = VkBotLongPoll(self.vk_session, '193158607')
        self.vk = self.vk_session.get_api()

        self.func_dict = {  # словарь функций - что вызывать в ответ на команды игрока
            msg_begin: self.begin_game,
            msg_join: self.join_session,
            msg_leave: self.leave_game,
            msg_done: self.done_pass_check,
            msg_pass: self.done_pass_check,
            msg_results: self.results,
            msg_settings: self.start_settings,
            msg_random_hat: self.random_hat,
            msg_current_hat: self.current_hat,
            msg_custom_hat: self.custom_hat,
            msg_change_easy: self.input_change,
            msg_change_medium: self.input_change,
            msg_change_difficult: self.input_change,
            msg_let_input: self.input_change,
            msg_stop_settings: self.stop_settings,
            msg_null_results: self.null_results,
            msg_queue: self.queue_turn,
            msg_add_words: self.add_words
        }

        self.event = None
        # информация о происходящем событии
        self.player_id = None
        # id игрока

        self.sessions = {}
        # для каждого ключа, кода сессии, значение - массив из 5 полей
        # нулевое поле - массив игроков, участвующих в игре
        #       нулевой игрок - администратор
        # первое поле - два массива:
        #       первый массив - массив слов, которые положили в шляпу из базы
        #       второй массив - массив слов, добавленные игроками
        # второе поле - массив из четырех элементов, -1 - если сейчас ожидается ввод числа слов такого типа:
        #       нулевое поле - начальное количество легких слов
        #       первое поле - начальное количество средних слов
        #       второе поле - начальное количество сложных слов
        #       третье поле - количество слов, которые может ввести каждый игрок
        # третье поле - идет ли сейчас ход, 0 - не идет, 1 - идет
        # четвертое поле - id следующего игрока в очереди

        self.players = {}
        # Для каждого ключа, id игрока, значение - массив из 4 полей
        # нулевое поле - в какой сессии участвует игрок
        # первое поле - массив флагов:
        #       нулевое поле - последняя клавиатура, чтобы вызывать при msg_wtf
        #       первое поле - флаг времени игрока, если оно 0 - значит не прошло, а если 1 - слова выдаваться не будут
        #       второе поле - последнее слово - чтобы возвращать в шляпу, если не угадать
        #       третье поле - флаг пишущего game code игрока: 0 - не пишет, 1 - сейчас должен написать
        #       четвертое поле - уникальный код хода
        #       пятое поле - количество очков игрока
        #       шестое поле - является ли администртором сессии: 0 - нет, 1 - да
        #       седьмое поле - флаг игрока, который может ввести слова: 0 - не может, 1 - может,
        #                       2 - это админ, который вводит количесвто слов, 3 - ожидаем ввода
        #       восьмое поле - 0, если текущее слово взято из случайной шляпы, 1 - если из кастомной
        # второе поле - имя игрока
        # третье поле - peer_id игрока

    def msg_send(self, message, keyboard=None, peer=None):  # отправление сообщения
        if peer is None:
            peer = self.event.obj.peer_id
        self.vk.messages.send(
            peer_id=peer,
            random_id=get_random_id(),
            message=message,
            keyboard=keyboard
        )
        if self.player_id in self.players:
            self.players[self.player_id][1][0] = keyboard

    def null_flag(self):  # обнуляем флаги игрока, дйствующие при ходе
        self.players[self.player_id][1][1] = 0
        self.players[self.player_id][1][2] = None
        self.players[self.player_id][1][3] = 0
        self.players[self.player_id][1][4] = -1
        self.players[self.player_id][1][8] = -1
        self.sessions[self.players[self.player_id][0]][3] = 0  # показываем что ход закончен

    def del_player(self):  # удаляем игрока
        self.players.pop(self.player_id)

    def end_turn(self):
        self.next_queue()
        self.null_flag()
        peer = self.players[self.sessions[self.players[self.player_id][0]][4]][3]
        self.return_lobby(msg_end_turn)
        self.msg_send(msg_next, peer=peer)

    def null_results(self):
        if self.players[self.player_id][1][6] == 1:
            player_session = self.sessions[self.players[self.player_id][0]]
            for player in player_session[0]:
                self.players[player][1][5] = 0
            self.msg_send(msg_null_results_done, settings_keyboard)
        else:
            self.msg_send(msg_not_admin, lobby_keyboard)

    def begin_game(self):  # начальный экран
        self.leave_session()  # уходим из сессии если игрок в ней состоит
        self.players[self.player_id] = [None, [None, 0, None, 1, -1, 0, 0, 0, -1], '', self.event.obj.peer_id]
        user_information = self.vk.users.get(user_ids=self.player_id)[0]
        user_name = user_information['first_name'] + ' ' + user_information['last_name']
        self.players[self.player_id][2] = user_name  # регистрация игрока и ставим флаг, что ждем game code
        self.msg_send(msg_begin_response)

    def next_queue(self):
        player = self.players[self.player_id]
        i = self.sessions[player[0]][0].index(self.player_id)
        self.sessions[player[0]][4] = self.sessions[player[0]][0][(i + 1) % len(self.sessions[player[0]][0])]

    def next_leave(self):
        player = self.players[self.player_id]
        player_session = self.sessions[player[0]]
        if player_session[4] == self.player_id:  # если он следующий, то берем следующего
            self.next_queue()
            peer = self.players[player_session[4]][3]
            if player_session[4] != self.player_id:  # если он один в игре, то не пишем ничего
                self.msg_send(msg_next, peer=peer)
            if player[1][4] != -1:  # если был его ход, то заканчиваем
                player_session[3] = 0

    def leave_session(self):  # выход игрока из сессии
        if self.player_id in self.players:
            player = self.players[self.player_id]
            if player[0] is not None:  # если игрок состоит в какой-то сессии
                player_session = self.sessions[player[0]]  # узнаем сессию игрока и удаляем его из players
                self.next_leave()
                player_session[0].remove(self.player_id)  # удаляем игрока из массива участников сессии
                if len(player_session[0]) == 0:  # если в сессии не осталось игроков, то удаляем и ее
                    self.sessions.pop(player[0])
                else:
                    self.players[player_session[0][0]][1][6] = 1  # передаем администраторские права
            self.del_player()  # удаляем игрока

    def already_playing(self, game_code):
        player_session = self.sessions[game_code][0]
        player_list = ''
        players_quantity = len(player_session)-1
        for i in range(players_quantity):
            player_id_in_session = player_session[i]
            player_list += (self.players[player_id_in_session][2] + '\n')
        if players_quantity == 1:
            self.msg_send(msg_already_playing_mono + '\n' + player_list, lobby_keyboard)
        else:
            self.msg_send(msg_already_playing_poly + '\n' + player_list, lobby_keyboard)

    def join_session(self):  # вход в сессию или создание новой
        game_code = self.event.obj.text
        # self.leave_session()  # если был в других сессиях, то выходим из них

        if game_code in self.sessions:  # если сессия уже есть, то добавляем в нее игрока
            self.sessions[game_code][0].append(self.player_id)
            self.players[self.player_id][0] = game_code  # добавляем игрока в сессию
            self.msg_send(msg_join_response + game_code, lobby_keyboard)
            self.already_playing(game_code)

        else:  # если ее нет, то создаем ее
            self.sessions[game_code] = [[self.player_id], [[], []], [0, 0, 0, 0], 0, self.player_id]
            self.players[self.player_id][0] = game_code  # добавляем игрока в сессию в качестве администратора
            self.players[self.player_id][1][6] = 1  # присваеваем игроку флаг администратора
            self.random_hat()  # создаем шляпу случайным образом
            self.msg_send(msg_join_response_admin + game_code, admin_lobby_keyboard)

    def return_lobby(self, message=None):  # возвращает игрока в лобби
        if self.players[self.player_id][1][6] == 1:
            return self.msg_send(message, admin_lobby_keyboard)
        else:
            return self.msg_send(message, admin_lobby_keyboard)

    def start_game(self):  # начало хода
        player_id = self.player_id
        if self.sessions[self.players[player_id][0]][3] == 0 and \
                self.sessions[self.players[player_id][0]][4] == self.player_id:  # начинаем ход, только если он не идет
            self.sessions[self.players[player_id][0]][3] = 1  # меняем флаг, что в сессии идет ход
            self.players[player_id][1][4] = random.random()  # создаем рандомный код этого хода
            this_turn = self.players[player_id][1][4]
            self.give_word()  # даем ему слово
            time.sleep(20)  # ждем 20 секунд, в это время могут приходить новые слова, на которые игрок отвечает
            if player_id in self.players and \
                    this_turn == self.players[player_id][1][4]:  # если игрок не закончил тот ход, то продолжаем
                self.players[player_id][1][1] = 1  # у игрока Время - теперь он не будет получать слова
                self.msg_send(msg_time, game_keyboard, self.players[player_id][3])
                time.sleep(3)  # ждем 3 секунды
                if player_id in self.players and this_turn == self.players[player_id][1][4]:
                    # опять же, если не закончил еще тот ход, то продолжаем
                    self.msg_send(msg_stop, game_keyboard, self.players[player_id][3])
        else:
            self.return_lobby(msg_turn_going)

    def give_word(self):  # функция выдачи игроку слова
        remaining_random = self.sessions[self.players[self.player_id][0]][1][0]
        remaining_custom = self.sessions[self.players[self.player_id][0]][1][1]
        words_remaining = remaining_random + remaining_custom  # массив оставшихся слов
        if len(words_remaining) > 0:  # если еще остались слова
            i_word = random.randint(0, len(words_remaining) - 1)
            new_word = words_remaining[i_word]  # выбираем случайное слово
            if i_word < len(remaining_random):
                self.players[self.player_id][1][8] = 0
                del remaining_random[i_word]
            else:
                self.players[self.player_id][1][8] = 1
                del remaining_custom[i_word-len(remaining_random)]
            self.players[self.player_id][1][2] = new_word  # записываем последнее выданное слово
            self.msg_send(new_word, game_keyboard)
        else:  # если слов не осталось
            self.next_queue()
            self.null_flag()
            self.return_lobby(msg_zero_words)

    def done_word(self):  # функция угадывания слова
        self.players[self.player_id][1][5] += 1  # увеличиваем счет игрока
        if self.players[self.player_id][1][1] == 0:  # если время еще есть, то даем еще одно слово
            self.give_word()
        else:  # если время закончилось, то отправляем в лобби
            self.end_turn()

    def pass_word(self):  # функция заканчивания хода
        last_word = self.players[self.player_id][1][2]  # берем последнее слово игрока
        if last_word is not None:  # если оно было
            if self.players[self.player_id][1][8] == 0:
                self.sessions[self.players[self.player_id][0]][1][0].append(last_word)  # возвращаем слово в шляпу
            else:
                self.sessions[self.players[self.player_id][0]][1][1].append(last_word)  # возвращаем слово в шляпу
        self.end_turn()

    def done_pass_check(self):  # функция проверки условий на done/pass
        if self.players[self.player_id][1][4] != -1:  # только если идет ход
            if self.event.obj.text == msg_done:  # смотрим что именно
                self.done_word()
            else:
                self.pass_word()
        else:  # нужно начать ход
            self.return_lobby(msg_need_start)

    def leave_game(self):  # выход из игры
        self.leave_session()  # выходим из сессии
        self.msg_send(msg_leave_response)

    def results(self):
        player_session = self.sessions[self.players[self.player_id][0]]
        player_results = ''
        for i in range(len(player_session[0])):
            player_id_in_session = player_session[0][i]
            player_points = str(self.players[player_id_in_session][1][5])
            player_results += (self.players[player_id_in_session][2] + ': ' + player_points + '\n')
            # пишем на каждой строчке - имя и количество очков каждого игрока из сессии
        self.return_lobby(player_results)

    def queue_turn(self):
        player_session = self.sessions[self.players[self.player_id][0]]
        player_queue = ''
        for i in range(len(player_session[0])):
            player_id_in_session = player_session[0][i]
            if player_session[4] == player_id_in_session:
                player_queue += '  ->'
            player_queue += (self.players[player_id_in_session][2] + '\n')
            # пишем на каждой строчке - имя каждого игрока из сессии
        self.return_lobby(player_queue)

    @admin_required
    def start_settings(self):  # функция настроек, доступная только администратору
        self.msg_send(msg_start_settings, settings_keyboard)

    @admin_required
    def stop_settings(self):  # завершение настроек шляпы
        self.msg_send(msg_custom_hat_created, admin_lobby_keyboard)

    @admin_required
    def custom_hat(self):  # создаем индивидуальную шляпу
        player_session = self.sessions[self.players[self.player_id][0]]
        number_words = msg_number_easy + str(player_session[2][0]) + \
            ', ' + msg_number_medium + str(player_session[2][1]) + ', ' + \
            msg_number_difficult + str(player_session[2][2])
        self.msg_send(number_words, customizing_keyboard)

    def make_custom_change(self, words_numb):
        player_session = self.sessions[self.players[self.player_id][0]]
        index_flag = player_session[2].index(-1)
        player_session[2][index_flag] = words_numb
        self.put_words()
        number_words = msg_number_easy + str(player_session[2][0]) + \
            ', ' + msg_number_medium + str(player_session[2][1]) + ', ' + \
            msg_number_difficult + str(player_session[2][2])
        self.msg_send(number_words, customizing_keyboard)

    def input_rank(self, rank):
        player_session = self.sessions[self.players[self.player_id][0]]
        # проверяем, завершил ли игрок предыдущий ввод
        if -1 not in player_session[2]:
            player_session[2][rank] = -1
            self.msg_send(msg_input[rank])
        else:
            self.msg_send(msg_input_going)

    def activate_input(self):  # теперь каждый игрок может вводить слова
        player_session = self.sessions[self.players[self.player_id][0]]
        player_session[1][1] = []
        for player in player_session[0]:  # теперь каждый игрок может вводить слова
            self.players[player][1][7] = 1
        self.players[player_session[0][0]][1][7] = 2  # админу даем право ввести количество слов
        self.msg_send(msg_add_how_many)

    def add_words(self):  # говорим игроку, сколько слов он может ввести
        player_session = self.players[self.player_id][0]
        words_quantity = self.sessions[player_session][2][3]
        if self.players[self.player_id][1][7] == 1 and words_quantity != 0:  # проверяем, может ли он вводить слова
            self.msg_send(msg_add_words_quantity + str(words_quantity))
            self.msg_send(msg_how_to_add_words)
            self.players[self.player_id][1][7] = 3
        elif self.players[self.player_id][1][6] == 1:  # говорим, что ввод слов запрещен
            self.return_lobby(msg_add_words_denied_admin)
            self.players[self.player_id][1][7] = 0
        else:
            self.return_lobby(msg_add_words_denied)
            self.players[self.player_id][1][7] = 0

    @admin_required
    def input_change(self):
        rank = self.event.obj.text
        if rank == msg_change_easy:
            i = 0
        elif rank == msg_change_medium:
            i = 1
        elif rank == msg_change_difficult:
            i = 2
        elif rank == msg_let_input:
            i = 3
            self.activate_input()
        else:
            return
        if i != 3:
            self.input_rank(i)

    def adding_custom_words(self):
        word_list = self.event.obj.text.split()  # переводим введенную строку в список
        player_session = self.players[self.player_id][0]
        if len(word_list) > self.sessions[player_session][2][3]:  # смотрим, не длинноват ли список
            self.msg_send(msg_try_again_adding)
        else:
            self.sessions[player_session][1][1] += word_list
            self.players[self.player_id][1][7] = 0  # теперь человек больше не может ничего ввести
            self.return_lobby(msg_adding_done)

    def put_words(self):
        player_session = self.sessions[self.players[self.player_id][0]]
        player_session[1][0] = []
        player_session[1][0] += random.sample(words_easy, k=player_session[2][0])
        player_session[1][0] += random.sample(words_medium, k=player_session[2][1])
        player_session[1][0] += random.sample(words_hard, k=player_session[2][2])

    @admin_required
    def current_hat(self):  # игра продолжается с текущей шляпой
        self.msg_send(msg_current_hat_played, admin_lobby_keyboard)

    @admin_required
    def random_hat(self):  # создается шляпа по умолчанию
        player_session = self.sessions[self.players[self.player_id][0]]
        player_session[2] = [100, 100, 100, 0]
        self.put_words()
        self.msg_send(msg_random_hat_created, admin_lobby_keyboard)  # возвращаем адмнистратора в админ. лобби

    @admin_required
    def input_numb(self):
        number = self.event.obj.text
        if number.isdigit():  # ввели число
            number = int(number)
            if number > 1000:  # проверим, не очень ли большое число ввели
                self.msg_send(msg_too_big_int)
                number = 1000
            if self.players[self.player_id][1][7] == 2:
                self.sessions[self.players[self.player_id][0]][2][3] = number
                self.sessions[self.players[self.player_id][0]][1][1] = []
                self.players[self.player_id][1][7] = 1
                self.return_lobby(msg_now_adding_possible + str(number))
            else:
                self.make_custom_change(number)
        else:  # если ввел не число, говорим, что надо ввести число
            self.msg_send(msg_not_int)

    def bot_respond(self):  # функция проверки всех событий
        for temp_event in self.long_poll.listen():
            # print(self.players)
            # print(self.sessions)
            if temp_event.type == VkBotEventType.MESSAGE_NEW:  # смотрим все новые сообщения
                self.event = temp_event
                self.player_id = self.event.obj.from_id
                if self.event.obj.text == msg_begin:
                    self.begin_game()
                elif self.player_id in self.players:
                    if self.players[self.player_id][0] is not None:
                        if (-1 in self.sessions[self.players[self.player_id][0]][2]
                                or self.players[self.player_id][1][7] == 2)\
                                and self.players[self.player_id][1][6] == 1:
                            self.input_numb()
                        elif self.players[self.player_id][1][7] == 3 and self.event.obj.text != msg_add_words:
                            self.adding_custom_words()
                        elif self.event.obj.text in self.func_dict:
                            self.func_dict[self.event.obj.text]()
                        elif self.event.obj.text == msg_start:  # если старт - то запускаем на поток, чтобы время шло
                            _thread.start_new_thread(self.start_game, ())
                        else:
                            self.msg_send(msg_wtf, keyboard=self.players[self.player_id][1][0])
                    elif self.players[self.player_id][1][3] == 1 \
                            and len(self.event.obj.text) < 10:  # условие того, что нам присылают код
                        self.func_dict[msg_join]()
                    else:
                        self.msg_send(msg_need_join)
                else:
                    self.msg_send(msg_need_begin, begin_keyboard)
